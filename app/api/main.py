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
from sqlalchemy.orm import Session

from app.api.routes_review import router as review_router
from app.db.database import Base, engine, get_db
import app.db.models  # noqa: F401 — registers all tables on Base.metadata before create_all
from app.db.models import AuditTrail, EvidenceLog, Obligation, Task
from app.embeddings.qdrant_client import find_by_obligation_id, get_client
from app.graph.build_graph import build_graph
from app.ingestion.clause_splitter import split_into_clauses
from app.ingestion.pdf_cleaner import extract_and_clean
from app.services.gap_engine import get_gaps, update_all_task_statuses
from app.services.supersession import mark_superseded_obligations


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/upload")
def upload_circular(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("data/raw_pdfs", exist_ok=True)
    file_path = f"data/raw_pdfs/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    circular_id = os.path.splitext(file.filename)[0]

    try:
        cleaned_text = extract_and_clean(file_path)
    except Exception as exc:
        # Fail fast here, before build_graph() ever runs, so a bad/unreadable
        # PDF doesn't pay the cost of opening a real Postgres checkpointer
        # connection for a request that can't proceed anyway.
        raise HTTPException(
            status_code=422, detail=f"PDF cleaning failed: {exc}"
        ) from exc

    clauses = split_into_clauses(cleaned_text)
    if not clauses:
        return {
            "status": "success",
            "filename": file.filename,
            "circular_id": circular_id,
            "clauses_processed": 0,
            "results": [],
        }

    graph = build_graph()
    results = []
    matched_obligation_ids = set()

    for i, clause_text in enumerate(clauses):
        clause_id = f"clause-{i}"
        state = {
            "circular_id": circular_id,
            "clause_id": clause_id,
            "raw_clause": clause_text,
            "heading": None,
        }
        config = {"configurable": {"thread_id": f"{circular_id}:{clause_id}"}}

        from langgraph.errors import GraphInterrupt
        try:
            result = graph.invoke(state, config=config)
        except GraphInterrupt as exc:
            state_val = graph.get_state(config).values
            similarity_match = state_val.get("similarity_match") or {}
            obligation_id = (similarity_match.get("payload") or {}).get("obligation_id")
            if obligation_id:
                matched_obligation_ids.add(obligation_id)
            results.append({"clause_id": clause_id, "status": "pending_review"})
            continue
        except Exception as exc:
            results.append({"clause_id": clause_id, "status": "error", "detail": str(exc)})
            continue

        if "__interrupt__" in result:
            # Paused for human review (amended/superseded clause). The old
            # obligation this clause matches is still active and awaiting a
            # decision — protect it from being wrongly marked superseded
            # below just because its review hasn't been submitted yet.
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
            # mapper_node deliberately no-ops on unchanged clauses (nothing to
            # update), but the obligation it matched is still current — count
            # it as matched so it isn't wrongly marked superseded below.
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

    # Only mark obligations superseded when every clause in this circular was
    # actually processed — a clause that errored out doesn't tell us whether
    # its obligation is still current, so treating a partial run as complete
    # coverage would risk wrongly superseding obligations that just failed to
    # re-match due to the error, not because they were genuinely dropped.
    had_errors = any(r["status"] == "error" for r in results)
    superseded = []
    if not had_errors:
        superseded = mark_superseded_obligations(db, circular_id, matched_obligation_ids)

    return {
        "status": "success",
        "filename": file.filename,
        "circular_id": circular_id,
        "clauses_processed": len(clauses),
        "results": results,
        "superseded_obligation_ids": superseded,
        "supersession_skipped_due_to_errors": had_errors,
    }


@app.post("/import/obligations")
def import_obligations_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
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
            
            # Create obligation
            ob_id = str(uuid.uuid4())
            obligation = Obligation(
                id=ob_id,
                clause_id=f"csv-import-{ob_id[:8]}",
                requirement=requirement,
                frequency=freq,
                evidence_type=evidence,
                deadline_rule=deadline_rule,
                intermediary=intermediary,
                status="active"
            )
            db.add(obligation)
            db.flush()
            
            # Create task
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
        return {"status": "success", "imported": imported_count}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"CSV processing failed: {str(exc)}")


@app.get("/gaps")
def list_gaps(db: Session = Depends(get_db)):
    try:
        return get_gaps(db)
    except Exception as exc:
        # Same note as above — narrow once app.db.models is real.
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.get("/obligations")
def list_obligations(db: Session = Depends(get_db)):
    update_all_task_statuses(db)
    client = get_client()

    obligations = []
    for ob in db.query(Obligation).filter(Obligation.status == "active").all():
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
        })
    return obligations


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
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "obligation_id": task.obligation_id,
        "description": entry.file_ref,
        "submitted_at": entry.submitted_at.isoformat(),
    }


_AUDIT_ACTION_LABELS = {
    "finalize": "Obligations extracted",
    "human_review": "Human review decision",
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
