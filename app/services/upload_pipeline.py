"""Circular upload pipeline: parse a PDF, then run every clause through the graph.

Split in two so the HTTP layer can reject a bad PDF immediately (``parse_circular``)
and run the slow, LLM-bound part (``process_chunks``) in a background job.
"""
import datetime
import logging
import time
import uuid
from typing import Callable

from sqlalchemy.orm import Session

from app.db.models import Circular, Clause, Obligation, Section, SOURCE_REGULATORY
from app.graph.build_graph import build_graph
from app.ingestion.hybrid_parser import parse_pdf_structured
from app.services.metrics import metrics_collector
from app.services.supersession import mark_superseded_obligations
from app.services.workflow_state import WorkflowState, advance

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


def parse_circular(file_path: str) -> list[dict]:
    """Parse the PDF into structured chunks. Raises on an unreadable document."""
    return parse_pdf_structured(file_path)


def _prepopulate_lineage(db: Session, circular_id: str, chunks: list[dict]) -> dict[int, str]:
    circular = db.query(Circular).filter(Circular.id == circular_id).first()
    if not circular:
        db.add(Circular(
            id=circular_id,
            title=circular_id,
            issue_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        ))

    clause_uuid_map: dict[int, str] = {}
    section_map: dict[str, str] = {}
    for idx, chunk in enumerate(chunks):
        section_title = chunk.get("section") or "General"
        if section_title not in section_map:
            sec_uuid = str(uuid.uuid4())
            db.add(Section(id=sec_uuid, title=section_title, circular_id=circular_id))
            section_map[section_title] = sec_uuid

        clause_uuid = str(uuid.uuid4())
        db.add(Clause(
            id=clause_uuid,
            clause_number=chunk.get("clause") or f"{idx}",
            text=chunk["text"],
            page=chunk.get("page"),
            section_id=section_map[section_title],
        ))
        clause_uuid_map[idx] = clause_uuid
    db.commit()
    return clause_uuid_map


def _build_state(circular_id: str, clause_id: str, index: int, chunk: dict, clause_uuid: str | None) -> dict:
    heading = f"Clause {chunk['clause']}: {chunk['section']}" if chunk.get("clause") else chunk.get("section")
    return {
        "circular_id": circular_id,
        "clause_id": clause_id,
        "raw_clause": chunk["text"],
        "heading": heading or f"Clause {index}",
        "confidence": chunk.get("confidence", 1.0),
        "page": chunk.get("page"),
        "section": chunk.get("section"),
        "clause_num": chunk.get("clause"),
        "parent_clause": chunk.get("parent"),
        "block_type": chunk.get("type"),
        "clause_uuid": clause_uuid,
    }


def _interrupted_obligation_id(similarity_match: dict | None) -> str | None:
    return ((similarity_match or {}).get("payload") or {}).get("obligation_id")


def process_chunks(
    db: Session,
    *,
    filename: str,
    circular_id: str,
    chunks: list[dict],
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Run every chunk through the compliance graph and return the upload summary."""
    from langgraph.errors import GraphInterrupt

    total = len(chunks)
    if not chunks:
        return {
            "status": "success", "filename": filename, "circular_id": circular_id,
            "clauses_processed": 0, "results": [],
        }

    advance(WorkflowState.EXTRACTION_RUNNING, db)
    try:
        clause_uuid_map = _prepopulate_lineage(db, circular_id, chunks)
    except Exception:
        db.rollback()
        raise

    graph = build_graph()
    results: list[dict] = []
    matched_obligation_ids: set[str] = set()

    for i, chunk in enumerate(chunks):
        clause_id = f"clause-{i}"
        state = _build_state(circular_id, clause_id, i, chunk, clause_uuid_map.get(i))
        config = {"configurable": {"thread_id": f"{circular_id}:{clause_id}"}}

        start = time.time()
        try:
            result = graph.invoke(state, config=config)
            metrics_collector.record_processing_time(time.time() - start)
        except GraphInterrupt:
            metrics_collector.record_processing_time(time.time() - start)
            obligation_id = _interrupted_obligation_id(graph.get_state(config).values.get("similarity_match"))
            if obligation_id:
                matched_obligation_ids.add(obligation_id)
            results.append({"clause_id": clause_id, "status": "pending_review"})
        except Exception as exc:
            metrics_collector.record_processing_time(time.time() - start)
            logger.exception("Clause %s of %s failed", clause_id, circular_id)
            results.append({"clause_id": clause_id, "status": "error", "detail": str(exc)})
        else:
            if "__interrupt__" in result:
                payload = result["__interrupt__"][0].value
                obligation_id = _interrupted_obligation_id(payload.get("similarity_match"))
                if obligation_id:
                    matched_obligation_ids.add(obligation_id)
                results.append({"clause_id": clause_id, "status": "pending_review"})
            else:
                task = result.get("task")
                if task:
                    matched_obligation_ids.add(task["obligation_id"])
                elif result.get("diff_status") == "unchanged":
                    obligation_id = _interrupted_obligation_id(result.get("similarity_match"))
                    if obligation_id:
                        matched_obligation_ids.add(obligation_id)
                results.append({
                    "clause_id": clause_id,
                    "status": "processed",
                    "diff_status": result.get("diff_status"),
                    "task": task,
                })

        if on_progress:
            on_progress(i + 1, total)

    had_errors = any(r["status"] == "error" for r in results)
    superseded: list[str] = []
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

    if any(r["status"] == "pending_review" for r in results):
        advance(WorkflowState.REVIEW_PENDING, db)
    elif not had_errors:
        advance(WorkflowState.REVIEW_APPROVED, db)

    return {
        "status": "success",
        "filename": filename,
        "circular_id": circular_id,
        "clauses_processed": total,
        "results": results,
        "superseded_obligation_ids": superseded,
        "supersession_skipped_due_to_errors": had_errors,
    }
