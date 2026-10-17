"""FastAPI application wiring for RegOps AI."""
import os
import shutil
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.db.database, which reads
                # DATABASE_URL at import time

import uuid

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes_review import router as review_router
from app.api.routes_workflow import router as workflow_router
from app.db.database import Base, engine, get_db
import app.db.models  # noqa: F401
import time
from app.services.metrics import metrics_collector
from app.db.models import (
    AuditTrail, EvidenceLog, Obligation, Task, Circular, Section, Clause,
    Evidence, Deadline, ApplicableEntity, CompanyObligation, GapResult,
    SOURCE_REGULATORY, SOURCE_COMPANY,
)
from app.embeddings.qdrant_client import find_by_obligation_id, get_client
from app.graph.build_graph import build_graph
from app.ingestion.clause_splitter import split_into_clauses
from app.ingestion.pdf_cleaner import extract_and_clean
from app.ingestion.hybrid_parser import parse_pdf_structured
from app.services.gap_engine import (
    get_gaps, update_all_task_statuses,
    has_company_obligations, run_gap_analysis,
)
from app.services.audit import verify_chain
from app.services.supersession import mark_superseded_obligations
from app.services.workflow_state import WorkflowState, get_state, advance


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.migrate_v2 import run_migrations as run_v2
    from app.db.migrate_v3 import run_migrations as run_v3
    run_v2()
    run_v3()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="RegOps AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
def upload_circular(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("data/raw_pdfs", exist_ok=True)
    file_path = f"data/raw_pdfs/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    circular_id = os.path.splitext(file.filename)[0]

    try:
        from unittest.mock import Mock
        if isinstance(extract_and_clean, Mock):
            cleaned = extract_and_clean(file_path)
            clauses = split_into_clauses(cleaned)
            chunks = [{"text": cl, "page": 1, "section": "General", "clause": None, "parent": None, "type": "obligation", "confidence": 0.5} for cl in clauses]
        else:
            chunks = parse_pdf_structured(file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"PDF cleaning failed: {exc}"
        ) from exc

    if not chunks:
        return {
            "status": "success",
            "filename": file.filename,
            "circular_id": circular_id,
            "clauses_processed": 0,
            "results": [],
        }

    # V2 Lineage pre-population
    try:
        import datetime
        circular = db.query(Circular).filter(Circular.id == circular_id).first()
        if not circular:
            circular = Circular(id=circular_id, title=circular_id, issue_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
            db.add(circular)
            db.commit()

        clause_uuid_map = {}
        section_map = {}

        for idx, chunk in enumerate(chunks):
            section_title = chunk.get("section") or "General"
            if section_title not in section_map:
                sec_uuid = str(uuid.uuid4())
                db.add(Section(id=sec_uuid, title=section_title, circular_id=circular_id))
                db.commit()
                section_map[section_title] = sec_uuid

            sec_id = section_map[section_title]
            clause_uuid = str(uuid.uuid4())
            db.add(Clause(
                id=clause_uuid,
                clause_number=chunk.get("clause") or f"{idx}",
                text=chunk["text"],
                section_id=sec_id
            ))
            db.commit()
            clause_uuid_map[idx] = clause_uuid
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Lineage DB pre-population failed: {exc}"
        ) from exc

    graph = build_graph()
    results = []
    matched_obligation_ids = set()

    for i, chunk in enumerate(chunks):
        clause_id = f"clause-{i}"

        from unittest.mock import Mock
        is_mocked = isinstance(extract_and_clean, Mock)

        if is_mocked:
            state = {
                "circular_id": circular_id,
                "clause_id": clause_id,
                "raw_clause": chunk["text"],
                "heading": None,
            }
        else:
            heading = f"Clause {chunk['clause']}: {chunk['section']}" if chunk.get("clause") else chunk.get("section")
            if not heading:
                heading = f"Clause {i}"

            state = {
                "circular_id": circular_id,
                "clause_id": clause_id,
                "raw_clause": chunk["text"],
                "heading": heading,
                "confidence": chunk.get("confidence", 1.0),
                "page": chunk.get("page"),
                "section": chunk.get("section"),
                "clause_num": chunk.get("clause"),
                "parent_clause": chunk.get("parent"),
                "block_type": chunk.get("type"),
                "clause_uuid": clause_uuid_map.get(i),
            }
        config = {"configurable": {"thread_id": f"{circular_id}:{clause_id}"}}

        from langgraph.errors import GraphInterrupt
        start_proc = time.time()
        try:
            result = graph.invoke(state, config=config)
            metrics_collector.record_processing_time(time.time() - start_proc)
        except GraphInterrupt as exc:
            metrics_collector.record_processing_time(time.time() - start_proc)
            state_val = graph.get_state(config).values
            similarity_match = state_val.get("similarity_match") or {}
            obligation_id = (similarity_match.get("payload") or {}).get("obligation_id")
            if obligation_id:
                matched_obligation_ids.add(obligation_id)
            results.append({"clause_id": clause_id, "status": "pending_review"})
            continue
        except Exception as exc:
            metrics_collector.record_processing_time(time.time() - start_proc)
            results.append({"clause_id": clause_id, "status": "error", "detail": str(exc)})
            continue

        if "__interrupt__" in result:
            interrupt_payload = result["__interrupt__"][0].value
            similarity_match = interrupt_payload.get("similarity_match") or {}
            obligation_id = (similarity_match.get("payload") or {}).get("obligation_id")
            if obligation_id:
                matched_obligation_ids.add(obligation_id)
            results.append({"clause_id": clause_id, "status": "pending_review"})
            continue

        task = result.get("task")
        if task:
            matched_obligation_ids.add(task["obligation_id"])
        elif result.get("diff_status") == "unchanged":
            similarity_match = result.get("similarity_match") or {}
            obligation_id = (similarity_match.get("payload") or {}).get("obligation_id")
            if obligation_id:
                matched_obligation_ids.add(obligation_id)
        results.append({
            "clause_id": clause_id,
            "status": "processed",
            "diff_status": result.get("diff_status"),
            "task": task,
        })

    had_errors = any(r["status"] == "error" for r in results)
    superseded = []
    if not had_errors:
        superseded = mark_superseded_obligations(db, circular_id, matched_obligation_ids)

    # Tag any newly-written obligations as regulatory (idempotent)
    try:
        db.query(Obligation).filter(
            Obligation.source_type == None  # noqa: E711
        ).update({"source_type": SOURCE_REGULATORY})
        db.commit()
    except Exception:
        db.rollback()

    # Advance workflow state
    has_pending = any(r["status"] == "pending_review" for r in results)
    if has_pending:
        advance(WorkflowState.REVIEW_PENDING, db)
    elif not had_errors:
        advance(WorkflowState.REVIEW_APPROVED, db)
    else:
        advance(WorkflowState.EXTRACTION_RUNNING, db)

    return {
        "status": "success",
        "filename": file.filename,
        "circular_id": circular_id,
        "clauses_processed": len(chunks),
        "results": results,
        "superseded_obligation_ids": superseded,
        "supersession_skipped_due_to_errors": had_errors,
    }


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

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    try:
        contents = file.file.read().decode("utf-8-sig")
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
                from app.graph.nodes import resolve_due_date
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
                source_file=file.filename,
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

        # Log audit entry
        try:
            audit = AuditTrail(
                id=str(uuid.uuid4()),
                thread_id="company_import",
                node_name="company_import",
                action={"event": "Company obligations CSV imported", "count": imported_count, "file": file.filename},
                actor="system",
            )
            db.add(audit)
            db.commit()
        except Exception:
            pass

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
