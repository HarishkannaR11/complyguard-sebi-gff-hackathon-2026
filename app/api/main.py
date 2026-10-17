"""FastAPI application wiring for RegOps AI."""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.db.database, which reads
                # DATABASE_URL at import time

import logging
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes_review import router as review_router
from app.api.routes_workflow import router as workflow_router
from app.api.security import cors_origins, read_upload, require_api_key, safe_filename
from app.db.database import SessionLocal, get_db
from app.db.migrate import run_migrations
import app.db.models  # noqa: F401
import time
from app.services.metrics import metrics_collector
from app.db.models import (
    AuditTrail, EvidenceLog, Obligation, Task, Circular, Section, Clause,
    Evidence, Deadline, ApplicableEntity, CompanyObligation, GapResult,
    SOURCE_REGULATORY, SOURCE_COMPANY, UploadJob,
)
from app.embeddings.qdrant_client import find_by_obligation_id, get_client
from app.services.gap_engine import (
    get_gaps, update_all_task_statuses,
    has_company_obligations, run_gap_analysis,
)
from app.graph.nodes import _write_audit_entry, resolve_due_date
from app.services.audit import verify_chain
from app.services.upload_jobs import create_job, fail_interrupted_jobs, job_to_dict, run_job
from app.services.upload_pipeline import parse_circular, process_chunks
from app.services.workflow_state import WorkflowState, get_state, advance


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    fail_interrupted_jobs(SessionLocal)
    yield


logger = logging.getLogger(__name__)

app = FastAPI(
    title="RegOps AI API",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,  # auth is a header (X-API-Key), not a cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)
app.include_router(workflow_router)


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    health_status = {
        "status": "healthy",
        "database": "unreachable",
        "qdrant": "unreachable",
    }

    try:
        db.execute(text("SELECT 1"))
        health_status["database"] = "reachable"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["database"] = f"error: {e}"

    try:
        get_client().get_collections()
        health_status["qdrant"] = "reachable"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["qdrant"] = f"error: {e}"

    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)

    return health_status


# ─────────────────────────────────────────────────────────────────────────────
# Readiness: tells the frontend what data exists
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    """
    Returns dataset availability flags so the frontend can conditionally
    render gap analysis sections only when company data exists.
    """
    has_regulatory = db.query(Obligation).filter(
        Obligation.status == "active",
        Obligation.source_type == SOURCE_REGULATORY
    ).first() is not None

    has_company = has_company_obligations(db)
    wf_state = get_state(db)
    ORDER = list(WorkflowState)

    return {
        "has_regulatory_obligations": has_regulatory,
        "has_company_obligations": has_company,
        "gap_analysis_available": has_regulatory and has_company,
        "workflow_state": wf_state.value,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 – Upload SEBI Circular → extract regulatory obligations
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/upload")
def upload_circular(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    wait: bool = False,
    db: Session = Depends(get_db),
):
    """Validate and parse the PDF now, then run the per-clause pipeline.

    By default the clause pipeline runs as a background job: this returns 202 with a
    ``job_id`` to poll at ``GET /jobs/{job_id}``. ``?wait=true`` runs it inline and
    returns the full result (used by scripts and tests).
    """
    data = read_upload(file, extension=".pdf", magic=b"%PDF-")
    filename = safe_filename(file.filename, default="circular.pdf")
    circular_id = os.path.splitext(filename)[0]

    os.makedirs("data/raw_pdfs", exist_ok=True)
    file_path = os.path.join("data/raw_pdfs", filename)
    with open(file_path, "wb") as buffer:
        buffer.write(data)

    try:
        chunks = parse_circular(file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"PDF cleaning failed: {exc}"
        ) from exc

    if wait or not chunks:
        try:
            return process_chunks(db, filename=filename, circular_id=circular_id, chunks=chunks)
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=500, detail=f"Lineage DB pre-population failed: {exc}"
            ) from exc

    job = create_job(db, filename=filename, circular_id=circular_id, total=len(chunks))
    background_tasks.add_task(run_job, SessionLocal, job.id, filename, circular_id, chunks)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": job.id,
            "circular_id": circular_id,
            "filename": filename,
            "clauses_total": len(chunks),
            "poll_url": f"/jobs/{job.id}",
        },
    )


@app.get("/jobs/{job_id}")
def get_upload_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(UploadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No such job '{job_id}'")
    return job_to_dict(job)


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 – Import Company Obligations CSV
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/import/obligations")
def import_obligations_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Import company obligations from CSV into the separate company_obligations table.
    Also writes legacy Obligation rows (source_type='company') for backward compat.
    """
    import csv
    import io
    import datetime

    raw = read_upload(file, extension=".csv")
    source_file = safe_filename(file.filename, default="obligations.csv")

    try:
        contents = raw.decode("utf-8-sig")
        csv_file = io.StringIO(contents)
        reader = csv.DictReader(csv_file)

        imported_count = 0
        for row in reader:
            requirement = row.get("requirement", "").strip()
            if not requirement:
                continue

            freq = row.get("frequency", "one-time").strip()
            evidence = row.get("evidence_type", "").strip()
            deadline_rule = row.get("deadline_rule", "").strip() or None
            intermediary = row.get("intermediary", "stockbroker").strip() or "stockbroker"
            owner = row.get("owner", "compliance").strip() or "compliance"

            due_date_str = row.get("due_date", "").strip()
            task_due_date = None
            if due_date_str:
                try:
                    task_due_date = datetime.datetime.fromisoformat(due_date_str)
                except ValueError:
                    pass

            if not task_due_date and deadline_rule:
                due_date_val = resolve_due_date(deadline_rule, datetime.date.today())
                if due_date_val:
                    task_due_date = datetime.datetime.combine(due_date_val, datetime.datetime.min.time())

            ob_id = str(uuid.uuid4())

            # ── Primary: CompanyObligation table ──────────────────────────
            co = CompanyObligation(
                id=ob_id,
                requirement=requirement,
                frequency=freq,
                evidence_type=evidence,
                deadline_rule=deadline_rule,
                intermediary=intermediary,
                owner=owner,
                due_date=task_due_date,
                status="open",
                source_file=source_file,
            )
            db.add(co)

            # ── Legacy: Obligation + Task (backward compat for /obligations) ──
            obligation = Obligation(
                id=ob_id,
                clause_id=f"csv-import-{ob_id[:8]}",
                requirement=requirement,
                frequency=freq,
                evidence_type=evidence,
                deadline_rule=deadline_rule,
                intermediary=intermediary,
                status="active",
                source_type=SOURCE_COMPANY,
            )
            db.add(obligation)
            db.flush()

            task = Task(
                id=str(uuid.uuid4()),
                obligation_id=ob_id,
                owner=owner,
                due_date=task_due_date,
                status="open"
            )
            db.add(task)
            imported_count += 1

        db.commit()

        # Advance workflow state
        advance(WorkflowState.COMPANY_DATA_IMPORTED, db)

        # Log audit entry (hash-chained like every other audit row)
        try:
            _write_audit_entry(
                thread_id="company_import",
                node_name="company_import",
                action={"event": "Company obligations CSV imported", "count": imported_count, "file": source_file},
                actor="system",
            )
        except Exception:
            logger.exception("Failed to write company-import audit entry")

        return {"status": "success", "imported": imported_count}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"CSV processing failed: {str(exc)}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 – Gap Analysis
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/gaps")
def list_gaps(db: Session = Depends(get_db)):
    """
    Returns gap analysis results (regulatory vs company obligations).
    Returns HTTP 400 if no company obligations have been uploaded.
    """
    try:
        result = run_gap_analysis(db)
        # Advance to DASHBOARD_READY on successful run
        advance(WorkflowState.DASHBOARD_READY, db)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.get("/gaps/legacy")
def list_gaps_legacy(db: Session = Depends(get_db)):
    """Legacy Task-based gap list for backward compatibility."""
    try:
        return get_gaps(db)
    except Exception as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Obligations (regulatory only)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/obligations")
def list_obligations(db: Session = Depends(get_db)):
    """Returns only regulatory obligations extracted from SEBI circulars."""
    update_all_task_statuses(db)
    client = get_client()

    obligations = []
    for ob in db.query(Obligation).filter(
        Obligation.status == "active",
        Obligation.source_type == SOURCE_REGULATORY,
    ).all():
        task = db.query(Task).filter(Task.obligation_id == ob.id).first()
        source = find_by_obligation_id(client, ob.id)
        obligations.append({
            "id": ob.id,
            "circular_name": (source or {}).get("circular_id"),
            "obligation_text": ob.requirement,
            "intermediary": ob.intermediary,
            "deadline": task.due_date.date().isoformat() if task and task.due_date else None,
            "evidence_type": ob.evidence_type,
            "source_chunk": (source or {}).get("text"),
            "status": task.status if task else "pending",
            "source_type": ob.source_type or SOURCE_REGULATORY,
        })
    return obligations


@app.get("/company-obligations")
def list_company_obligations(db: Session = Depends(get_db)):
    """Returns company obligations imported from CSV."""
    results = []
    for co in db.query(CompanyObligation).all():
        results.append({
            "id": co.id,
            "requirement": co.requirement,
            "frequency": co.frequency,
            "evidence_type": co.evidence_type,
            "deadline_rule": co.deadline_rule,
            "intermediary": co.intermediary,
            "owner": co.owner,
            "due_date": co.due_date.date().isoformat() if co.due_date else None,
            "status": co.status,
            "source_file": co.source_file,
            "imported_at": co.imported_at.isoformat() if co.imported_at else None,
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Evidence
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/evidence")
def list_evidence(db: Session = Depends(get_db)):
    results = []
    for e in db.query(EvidenceLog).all():
        task = db.query(Task).filter(Task.id == e.task_id).one_or_none()
        results.append({
            "id": e.id,
            "obligation_id": task.obligation_id if task else None,
            "description": e.file_ref,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        })
    return results


class EvidenceIn(BaseModel):
    obligation_id: str
    description: str


@app.post("/evidence")
def create_evidence(payload: EvidenceIn, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.obligation_id == payload.obligation_id).first()
    if not task:
        raise HTTPException(
            status_code=404, detail=f"No task found for obligation '{payload.obligation_id}'"
        )
    entry = EvidenceLog(id=str(uuid.uuid4()), task_id=task.id, file_ref=payload.description)
    db.add(entry)

    evidence_row = Evidence(
        id=entry.id,
        file_ref=payload.description,
        submitted_at=entry.submitted_at,
        obligation_id=payload.obligation_id
    )
    db.add(evidence_row)

    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "obligation_id": task.obligation_id,
        "description": entry.file_ref,
        "submitted_at": entry.submitted_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Audit Log
# ─────────────────────────────────────────────────────────────────────────────

_AUDIT_ACTION_LABELS = {
    "finalize": "Regulatory Extraction",
    "human_review": "Review Decision",
    "company_import": "Company Import",
    "gap_analysis": "Gap Analysis",
    "extractor": "Regulatory Extraction",
    "mapper": "Regulatory Extraction",
}


@app.get("/audit_log")
def list_audit_log(db: Session = Depends(get_db)):
    results = []
    for r in db.query(AuditTrail).order_by(AuditTrail.timestamp.desc()).all():
        detail = ", ".join(f"{k}={v}" for k, v in (r.action or {}).items())
        results.append({
            "id": r.id,
            "action": _AUDIT_ACTION_LABELS.get(r.node_name, r.node_name),
            "detail": detail,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        })
    return results


@app.get("/audit_log/verify")
def verify_audit_log(db: Session = Depends(get_db)):
    """Re-compute the whole hash chain and report the first tampered/missing entry."""
    return verify_chain(db)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import Response


@app.get("/metrics")
def get_metrics(format: str = "prometheus"):
    if format == "json":
        return metrics_collector.get_metrics_summary()

    prometheus_data = metrics_collector.get_prometheus_format()
    return Response(content=prometheus_data, media_type="text/plain")
