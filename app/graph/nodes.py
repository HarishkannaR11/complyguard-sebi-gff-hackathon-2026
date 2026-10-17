"""LangGraph pipeline nodes for the RegOps AI compliance-obligation pipeline."""
import hashlib
import html
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from datetime import datetime as dt_datetime

import os
import time
import threading
import re

from langgraph.types import interrupt

logger = logging.getLogger(__name__)

_audit_lock = threading.Lock()


def _thread_id(state) -> str:
    return f"{state.get('circular_id')}:{state.get('clause_id')}"


def parse_json_robust(content: str) -> dict:
    content = content.replace("```json", "").replace("```", "").strip()
    start_idx = content.find("{")
    end_idx = content.rfind("}") + 1
    if start_idx == -1 or end_idx == 0:
        raise ValueError(f"No JSON object found in response: {content}")
    
    raw_json = content[start_idx:end_idx]
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        # Fallback: remove trailing commas before closing braces/brackets
        fixed_json = re.sub(r',\s*([\]}])', r'\1', raw_json)
        try:
            return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to decode LLM JSON: {raw_json}. Error: {str(e)}")

from app.db.database import SessionLocal
from app.db.models import AuditTrail, EvidenceLog, Obligation, Task, Circular, Section, Clause, Evidence, Deadline, ApplicableEntity, ReviewQueue
from app.embeddings.embedder import embed_texts
from app.llm.groq_client import chat_completion
from app.services.audit import compute_audit_hash  # noqa: F401  (re-exported)
from app.embeddings.qdrant_client import ensure_collection, get_client, search, upsert_chunks
from app.services.metrics import metrics_collector

from .state import ComplianceState

FREQUENCY_DAYS = {
    "monthly": 30,
    "quarterly": 90,
    "annual": 365,
}


def chunker_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "chunker", _thread_id(state))
    raw_clause = state["raw_clause"].strip()
    heading = state.get("heading") or raw_clause.splitlines()[0][:80].strip()
    return {"raw_clause": raw_clause, "heading": heading}


def embedder_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "embedder", _thread_id(state))
    start = time.time()
    embedding = embed_texts([state["raw_clause"]])[0]
    metrics_collector.record_embedding_latency(time.time() - start)
    return {"embedding": embedding}


def resolve_due_date(deadline_rule: str | None, today: date) -> date | None:
    if not deadline_rule:
        return None
    try:
        return date.fromisoformat(deadline_rule)
    except ValueError:
        pass
    days = FREQUENCY_DAYS.get(deadline_rule.strip().lower())
    if days is None:
        return None
    return today + timedelta(days=days)


EXTRACTION_PROMPT = """
You are a regulatory compliance AI. Read the SEBI circular clause below and extract
the single compliance obligation it imposes.

Return the result strictly as a JSON object matching this schema:
{{
    "requirement": "Clear description of what must be done",
    "frequency": "How often this recurs (e.g. one-time, monthly, quarterly, annual)",
    "evidence_type": "What proof is needed to show compliance",
    "deadline_rule": "An ISO date YYYY-MM-DD if the clause gives a specific calendar date, a recognized frequency keyword (monthly/quarterly/annual) if it recurs on a schedule with no fixed date, or null if open-ended with no deadline",
    
    "deadline_confidence": <float confidence score for deadline extraction between 0.0 and 1.0>,
    "entity_confidence": <float confidence score for target entity identification between 0.0 and 1.0>,
    "evidence_confidence": <float confidence score for evidence type extraction between 0.0 and 1.0>,
    "overall_confidence": <float overall extraction confidence score between 0.0 and 1.0>
}}

Do not include any other text in your response, only the JSON object.

Clause to analyze:
{clause_text}
"""


def extractor_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "extractor", _thread_id(state))
    prompt = EXTRACTION_PROMPT.format(clause_text=state["raw_clause"])

    start = time.time()
    content = chat_completion(prompt)
    metrics_collector.record_llm_latency(time.time() - start)

    obligation = parse_json_robust(content)
    return {"extracted_obligation": obligation}


from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class ExtractedObligation(BaseModel):
    requirement: str
    frequency: str
    evidence_type: str
    deadline_rule: Optional[str] = None
    
    deadline_confidence: float
    entity_confidence: float
    evidence_confidence: float
    overall_confidence: float
    
    @field_validator("requirement", "frequency", "evidence_type")
    @classmethod
    def check_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or whitespace only")
        return v.strip()
        
    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        freqs = {"one-time", "monthly", "quarterly", "annual"}
        if v.lower().strip() not in freqs:
            raise ValueError(f"Invalid frequency: {v}. Must be one of {freqs}")
        return v.lower().strip()
        
    @field_validator("deadline_rule")
    @classmethod
    def validate_deadline_rule(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v_clean = v.lower().strip()
        if v_clean in {"one-time", "monthly", "quarterly", "annual"}:
            return v_clean
        try:
            date.fromisoformat(v_clean)
            return v_clean
        except ValueError:
            raise ValueError(f"Invalid deadline rule: {v}. Must be an ISO date or frequency keyword")

    @field_validator("deadline_confidence", "entity_confidence", "evidence_confidence", "overall_confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v):
        if v is None:
            return 0.0
        try:
            val = float(v)
            if val > 1.0:
                val = val / 100.0
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            raise ValueError(f"Confidence score must be a number: {v}")


def validation_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "validation", _thread_id(state))
    extracted = state.get("extracted_obligation")
    errors = []
    warnings = []
    overall_conf = 0.0
    
    if not extracted:
        errors.append("No obligation extracted by LLM.")
    else:
        try:
            validated = ExtractedObligation(**extracted)
            overall_conf = validated.overall_confidence
            
            if overall_conf < 0.80:
                errors.append(f"Overall confidence {overall_conf:.2f} is below 80% threshold.")
            elif overall_conf < 0.95:
                warnings.append(f"Warning: Overall confidence {overall_conf:.2f} is between 80% and 95%.")
        except Exception as e:
            if hasattr(e, "errors"):
                for err in e.errors():
                    errors.append(f"Field '{err['loc'][0]}': {err['msg']}")
            else:
                errors.append(str(e))
                
    validation_status = "passed" if not errors else "failed"
    retries = state.get("extraction_retries") or 0
    next_retries = retries + 1 if validation_status == "failed" else retries
    
    # Track metrics
    if validation_status == "failed":
        metrics_collector.increment_validation_failures()
        metrics_collector.increment_retry_count()
    metrics_collector.record_confidence(overall_conf)
    
    return {
        "validation_status": validation_status,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "overall_confidence": overall_conf,
        "extraction_retries": next_retries
    }


COMPARISON_PROMPT = """
You are a regulatory compliance AI. Your task is to compare a new regulatory clause against candidate clauses from older circulars to check for changes.

For the new clause, identify if it matches any of the candidates, and classify the relationship as:
- UNCHANGED: The new clause is identical or semantically identical to a candidate with no material changes to the requirement.
- AMENDED: The new clause modifies a candidate (e.g. changes in deadlines, frequencies, wording, or scope, but refers to the same underlying obligation).
- SUPERSEDED: The new clause explicitly replaces or overrides a candidate.
- NEW: The new clause represents a completely new obligation not covered by any candidate.

Candidates:
{candidates_text}

New Clause:
{new_clause_text}

Return your answer strictly as a JSON object with this schema:
{{
  "status": "UNCHANGED" | "AMENDED" | "SUPERSEDED" | "NEW",
  "confidence": <float confidence score between 0.0 and 1.0>,
  "matched_obligation_id": "<obligation_id of the matching candidate, or null if NEW>",
  "changes": ["requirement" | "frequency" | "evidence_type" | "deadline_rule" | ...] or [] if UNCHANGED/NEW,
  "reason": "<Detailed explanation comparing the two, explaining the changes or why it is new>"
}}

Do not include any conversational text or markdown formatting except the JSON object.
"""


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def differ_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "differ", _thread_id(state))
    client = get_client()
    ensure_collection(client, vector_size=len(state["embedding"]))
    
    # Stage 1: Retrieve top-3 candidates (limit = 3)
    start_search = time.time()
    hits = search(client, state["embedding"], limit=3)
    metrics_collector.record_vector_search_latency(time.time() - start_search)
    
    if not hits:
        return {
            "diff_status": "new",
            "similarity_match": None,
            "diff_changes": [],
            "diff_reason": "No similar historical clauses found in vector database.",
            "diff_confidence": 1.0
        }

    # Build candidate descriptions for LLM comparison
    candidates_text = ""
    for idx, hit in enumerate(hits):
        payload = hit.get("payload") or {}
        obligation_id = payload.get("obligation_id", "N/A")
        clause_id = payload.get("clause_id", "N/A")
        text = hit.get("text", "N/A")
        score = hit.get("score", 0.0)
        candidates_text += f"\nCandidate {idx+1} [Score: {score:.3f}]:\n- Obligation ID: {obligation_id}\n- Clause ID: {clause_id}\n- Text: {text}\n"

    # Stage 2: Compare using LLM
    prompt = COMPARISON_PROMPT.format(
        candidates_text=candidates_text,
        new_clause_text=state["raw_clause"]
    )

    start_llm = time.time()
    content = chat_completion(prompt)
    metrics_collector.record_llm_latency(time.time() - start_llm)

    comparison = parse_json_robust(content)
    
    status_upper = comparison.get("status", "NEW").upper()
    confidence = comparison.get("confidence", 1.0)
    changes = comparison.get("changes", [])
    reason = comparison.get("reason", "")
    matched_id = comparison.get("matched_obligation_id")
    
    status_map = {
        "NEW": "new",
        "AMENDED": "amended",
        "SUPERSEDED": "superseded",
        "UNCHANGED": "unchanged"
    }
    diff_status = status_map.get(status_upper, "new")
    
    # Resolve the matching candidate hit
    similarity_match = None
    if diff_status != "new":
        if matched_id:
            for hit in hits:
                payload = hit.get("payload") or {}
                if payload.get("obligation_id") == matched_id:
                    similarity_match = hit
                    break
        # Fallback to the top candidate hit if it's not new and no ID match was resolved
        if not similarity_match and hits:
            similarity_match = hits[0]

    # Write audit trail entry
    thread_id = f"{state['circular_id']}:{state['clause_id']}"
    _write_audit_entry(
        thread_id=thread_id,
        node_name="differ",
        action={
            "status": status_upper,
            "confidence": confidence,
            "changes": changes,
            "reason": reason,
            "matched_obligation_id": matched_id
        },
        actor="system"
    )

    return {
        "diff_status": diff_status,
        "similarity_match": similarity_match,
        "diff_changes": changes,
        "diff_reason": reason,
        "diff_confidence": confidence
    }


def mapper_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "mapper", _thread_id(state))
    if state.get("human_decision") == "reject" or state.get("diff_status") == "unchanged":
        return {}

    obligation_data = state["extracted_obligation"]
    db = SessionLocal()
    try:
        obligation = None
        if state.get("diff_status") == "amended" and state.get("similarity_match"):
            obligation_id = state["similarity_match"]["payload"].get("obligation_id")
            if obligation_id:
                obligation = (
                    db.query(Obligation).filter(Obligation.id == obligation_id).one_or_none()
                )

        if obligation is None:
            obligation = Obligation(id=str(uuid.uuid4()), clause_id=state["clause_id"])
            db.add(obligation)

        obligation.requirement = obligation_data["requirement"]
        obligation.frequency = obligation_data["frequency"]
        obligation.evidence_type = obligation_data["evidence_type"]
        obligation.deadline_rule = obligation_data["deadline_rule"]
        
        # Lineage attributes
        obligation.origin_circular_id = state["circular_id"]
        obligation.clause_uuid = state.get("clause_uuid")
        
        diff_status = state.get("diff_status")
        matched_id = None
        if state.get("similarity_match"):
            matched_id = state["similarity_match"]["payload"].get("obligation_id")
            
        if diff_status == "amended" and matched_id:
            obligation.previous_obligation_id = matched_id
            obligation.amended_obligation_id = matched_id
        elif diff_status == "superseded" and matched_id:
            obligation.previous_obligation_id = matched_id
            obligation.superseded_obligation_id = matched_id

        db.flush()

        due_date_value = resolve_due_date(obligation_data.get("deadline_rule"), date.today())
        task_due_date = (
            dt_datetime.combine(due_date_value, dt_datetime.min.time())
            if due_date_value else None
        )
        
        # Backwards compatible Task
        task = Task(
            id=str(uuid.uuid4()),
            obligation_id=obligation.id,
            owner="compliance",
            due_date=task_due_date,
        )
        db.add(task)
        
        # Parallel V2 Deadline
        deadline = Deadline(
            id=str(uuid.uuid4()),
            due_date=task_due_date,
            status="open",
            obligation_id=obligation.id
        )
        db.add(deadline)

        # Parallel V2 ApplicableEntity
        entity = ApplicableEntity(
            id=str(uuid.uuid4()),
            entity_name=obligation.intermediary or "stockbroker",
            obligation_id=obligation.id
        )
        db.add(entity)

        db.commit()

        obligation_id, task_id = obligation.id, task.id
    finally:
        db.close()

    try:
        client = get_client()
        upsert_chunks(
            client,
            chunks=[state["raw_clause"]],
            vectors=[state["embedding"]],
            metadatas=[{
                "circular_id": state["circular_id"],
                "clause_id": state["clause_id"],
                "obligation_id": obligation_id,
            }],
        )
    except Exception:
        # Postgres and Qdrant can't share a transaction: the obligation is already
        # committed, so say how to repair the missing vector.
        logger.exception(
            "Obligation %s was saved but its vector was not written to Qdrant; "
            "run POST /admin/reconcile-vectors to repair it", obligation_id,
        )
        raise

    return {
        "task": {
            "id": task_id,
            "obligation_id": obligation_id,
            "due_date": str(due_date_value) if due_date_value else None,
        }
    }


def evidence_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "evidence check", _thread_id(state))
    task_info = state.get("task")
    if not task_info:
        return {"evidence_status": "missing"}

    db = SessionLocal()
    try:
        has_evidence = (
            db.query(EvidenceLog).filter(EvidenceLog.task_id == task_info["id"]).first()
            is not None
        )
    finally:
        db.close()

    return {"evidence_status": "present" if has_evidence else "missing"}


def gap_engine_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "gap engine", _thread_id(state))
    task_info = state.get("task")
    if not task_info:
        return {}

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_info["id"]).one_or_none()
        if task is None:
            return {}
        deadline = task.due_date.date().isoformat() if task.due_date else None
        from app.services.gap_engine import compute_status
        task.status = compute_status(has_evidence=False, deadline=deadline, today=date.today())
        db.commit()
        new_status = task.status
    finally:
        db.close()

    return {"task": {**task_info, "status": new_status}}


def _write_audit_entry(thread_id: str, node_name: str, action: dict, actor: str) -> None:
    # Thread-safe lock at the process level and SELECT FOR UPDATE at the DB level
    # to protect the hash chain from fork splits under concurrent writers.
    with _audit_lock:
        db = SessionLocal()
        try:
            last = db.query(AuditTrail).order_by(AuditTrail.timestamp.desc()).with_for_update().first()
            prev_hash = last.hash if last else ""
            timestamp = dt_datetime.now(timezone.utc).replace(tzinfo=None)
            entry_hash = compute_audit_hash(prev_hash, action, timestamp)
            db.add(AuditTrail(
                id=str(uuid.uuid4()),
                thread_id=thread_id,
                node_name=node_name,
                action=action,
                actor=actor,
                timestamp=timestamp,
                prev_hash=prev_hash,
                hash=entry_hash,
            ))
            db.commit()
        finally:
            db.close()


import difflib


def generate_text_diff(old_text: str, new_text: str) -> str:
    """Word-level diff as HTML. The result is rendered with innerHTML by the review UI and
    the words come from an uploaded PDF, so every word is HTML-escaped; only the <del>/<ins>
    wrappers added here are markup."""
    if not old_text:
        return html.escape(new_text)

    old_words = [html.escape(w) for w in old_text.split()]
    new_words = [html.escape(w) for w in new_text.split()]

    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    diff_html = []

    def deleted(words):
        return f"<del class='bg-red-100 text-red-700 line-through px-1 rounded'>{' '.join(words)}</del>"

    def inserted(words):
        return f"<ins class='bg-green-100 text-green-700 font-semibold px-1 rounded'>{' '.join(words)}</ins>"

    for opcode, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if opcode == 'equal':
            diff_html.append(" ".join(old_words[a_start:a_end]))
        elif opcode == 'replace':
            diff_html.append(deleted(old_words[a_start:a_end]))
            diff_html.append(inserted(new_words[b_start:b_end]))
        elif opcode == 'delete':
            diff_html.append(deleted(old_words[a_start:a_end]))
        elif opcode == 'insert':
            diff_html.append(inserted(new_words[b_start:b_end]))

    return " ".join(diff_html)


def human_review_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "human review", _thread_id(state))
    prev_text = None
    similarity_match = state.get("similarity_match")
    if similarity_match:
        prev_text = similarity_match.get("text")
        
    new_text = state.get("raw_clause") or ""
    diff = generate_text_diff(prev_text or "", new_text)
    
    # Save to ReviewQueue database table
    db = SessionLocal()
    try:
        thread_id = f"{state['circular_id']}:{state['clause_id']}"
        review_item = db.query(ReviewQueue).filter(ReviewQueue.id == thread_id).first()
        if not review_item:
            explanation = state.get("diff_reason")
            if not explanation and state.get("validation_errors"):
                explanation = ", ".join(state["validation_errors"])
                
            confidence = state.get("overall_confidence")
            if confidence is None and similarity_match:
                confidence = similarity_match.get("score")
                
            review_item = ReviewQueue(
                id=thread_id,
                circular_id=state["circular_id"],
                clause_id=state["clause_id"],
                previous_clause=prev_text,
                new_clause=new_text,
                highlighted_diff=diff,
                llm_explanation=explanation,
                confidence=confidence,
                extracted_obligation=state.get("extracted_obligation"),
                status="pending",
                clause_uuid=state.get("clause_uuid"),
                clause_number=state.get("clause_num"),
                section=state.get("section"),
                page=state.get("page"),
            )
            db.add(review_item)
            db.commit()
    finally:
        db.close()

    resume = interrupt({
        "clause_id": state["clause_id"],
        "extracted_obligation": state.get("extracted_obligation"),
        "diff_status": state.get("diff_status"),
        "similarity_match": state.get("similarity_match"),
        "previous_clause": prev_text,
        "new_clause": new_text,
        "highlighted_diff": diff,
        "llm_explanation": state.get("diff_reason") or (state.get("validation_errors") and ", ".join(state["validation_errors"])),
        "confidence": state.get("overall_confidence") or (similarity_match and similarity_match.get("score")),
    })
    decision = resume["decision"]
    actor = resume.get("actor", "unknown")

    extracted_obligation = state.get("extracted_obligation")
    human_decision = decision
    if decision.startswith("amend:"):
        amendment = json.loads(decision[len("amend:"):])
        extracted_obligation = {**(extracted_obligation or {}), **amendment}
        human_decision = "amend"

    # Update status in ReviewQueue table
    db = SessionLocal()
    try:
        thread_id = f"{state['circular_id']}:{state['clause_id']}"
        review_item = db.query(ReviewQueue).filter(ReviewQueue.id == thread_id).first()
        if review_item:
            review_item.status = "approved" if human_decision == "approve" else ("rejected" if human_decision == "reject" else "edited")
            review_item.extracted_obligation = extracted_obligation
            db.commit()
    except Exception as e:
        logger.warning("Failed to update ReviewQueue status for %s: %s", thread_id, e)
    finally:
        db.close()

    _write_audit_entry(
        thread_id=f"{state['circular_id']}:{state['clause_id']}",
        node_name="human_review",
        action={"decision": human_decision},
        actor=actor,
    )

    return {
        "extracted_obligation": extracted_obligation,
        "human_decision": human_decision,
    }


def finalize_node(state: ComplianceState) -> dict:
    logger.info("stage=%s thread=%s", "finalize", _thread_id(state))
    _write_audit_entry(
        thread_id=f"{state['circular_id']}:{state['clause_id']}",
        node_name="finalize",
        action={
            "obligation_id": (state.get("task") or {}).get("obligation_id"),
            "task_id": (state.get("task") or {}).get("id"),
            "diff_status": state.get("diff_status"),
            "human_decision": state.get("human_decision"),
        },
        actor="system",
    )
    return {}
