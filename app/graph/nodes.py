"""LangGraph pipeline nodes for the RegOps AI compliance-obligation pipeline."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta
from datetime import datetime as dt_datetime

import os
import time
import threading
import re

from groq import APIConnectionError, Groq
from langgraph.types import interrupt

_audit_lock = threading.Lock()


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
from app.db.models import AuditTrail, EvidenceLog, Obligation, Task
from app.embeddings.embedder import embed_texts
from app.embeddings.qdrant_client import ensure_collection, get_client, search, upsert_chunks

from .state import ComplianceState

FREQUENCY_DAYS = {
    "monthly": 30,
    "quarterly": 90,
    "annual": 365,
}


def chunker_node(state: ComplianceState) -> dict:
    raw_clause = state["raw_clause"].strip()
    heading = state.get("heading") or raw_clause.splitlines()[0][:80].strip()
    return {"raw_clause": raw_clause, "heading": heading}


def embedder_node(state: ComplianceState) -> dict:
    embedding = embed_texts([state["raw_clause"]])[0]
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


def compute_audit_hash(prev_hash: str, action: dict, timestamp: datetime) -> str:
    payload = prev_hash + json.dumps(action, sort_keys=True) + timestamp.isoformat()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_RETRIES = 3

EXTRACTION_PROMPT = """
You are a regulatory compliance AI. Read the SEBI circular clause below and extract
the single compliance obligation it imposes.

Return the result strictly as a JSON object matching this schema:
{{
    "requirement": "Clear description of what must be done",
    "frequency": "How often this recurs (e.g. one-time, monthly, quarterly, annual)",
    "evidence_type": "What proof is needed to show compliance",
    "deadline_rule": "An ISO date YYYY-MM-DD if the clause gives a specific calendar
        date, a recognized frequency keyword (monthly/quarterly/annual) if it recurs
        on a schedule with no fixed date, or null if open-ended with no deadline"
}}

Do not include any other text in your response, only the JSON object.

Clause to analyze:
{clause_text}
"""


def extractor_node(state: ComplianceState) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")

    client = Groq(api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(clause_text=state["raw_clause"])

    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except APIConnectionError:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(1.5 * (attempt + 1))

    content = response.choices[0].message.content
    obligation = parse_json_robust(content)
    return {"extracted_obligation": obligation}


SIMILARITY_THRESHOLD = 0.85


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def differ_node(state: ComplianceState) -> dict:
    client = get_client()
    ensure_collection(client, vector_size=len(state["embedding"]))
    hits = search(client, state["embedding"], limit=1)

    if not hits or hits[0]["score"] < SIMILARITY_THRESHOLD:
        return {"diff_status": "new", "similarity_match": None}

    top = hits[0]
    if _normalize(top["text"]) == _normalize(state["raw_clause"]):
        return {"diff_status": "unchanged", "similarity_match": top}
    return {"diff_status": "amended", "similarity_match": top}


def mapper_node(state: ComplianceState) -> dict:
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
        db.flush()

        due_date_value = resolve_due_date(obligation_data.get("deadline_rule"), date.today())
        task_due_date = (
            dt_datetime.combine(due_date_value, dt_datetime.min.time())
            if due_date_value else None
        )
        task = Task(
            id=str(uuid.uuid4()),
            obligation_id=obligation.id,
            owner="compliance",
            due_date=task_due_date,
        )
        db.add(task)
        db.commit()

        obligation_id, task_id = obligation.id, task.id
    finally:
        db.close()

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

    return {
        "task": {
            "id": task_id,
            "obligation_id": obligation_id,
            "due_date": str(due_date_value) if due_date_value else None,
        }
    }


def evidence_node(state: ComplianceState) -> dict:
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
            timestamp = dt_datetime.utcnow()
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


def human_review_node(state: ComplianceState) -> dict:
    resume = interrupt({
        "clause_id": state["clause_id"],
        "extracted_obligation": state.get("extracted_obligation"),
        "diff_status": state.get("diff_status"),
        "similarity_match": state.get("similarity_match"),
    })
    decision = resume["decision"]
    actor = resume.get("actor", "unknown")

    extracted_obligation = state.get("extracted_obligation")
    human_decision = decision
    if decision.startswith("amend:"):
        amendment = json.loads(decision[len("amend:"):])
        extracted_obligation = {**(extracted_obligation or {}), **amendment}
        human_decision = "amend"

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
