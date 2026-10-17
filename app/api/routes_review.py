"""Human-review API routes: resume a paused compliance-pipeline run with a decision."""
import json
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langgraph.types import Command

from app.api.security import Principal, require_api_key, resolve_actor
from app.db.database import get_db
from app.db.models import ReviewQueue
from app.graph.build_graph import build_graph

router = APIRouter()

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def async_resume_graph(thread_id: str, action: str, obligation_data: dict = None, actor: str = "reviewer"):
    try:
        graph = build_graph()
        config = {"configurable": {"thread_id": thread_id}}
        
        if action == "approve":
            decision = "approve"
        elif action == "reject":
            decision = "reject"
        elif action in ("edit", "amend"):
            decision = f"amend:{json.dumps(obligation_data)}"
        else:
            decision = "approve"
            
        graph.invoke(
            Command(resume={"decision": decision, "actor": actor}),
            config=config,
        )
    except Exception as e:
        print(f"[ERROR] Asynchronous resume failed for thread {thread_id}: {e}")


@router.get("/review/queue")
def get_review_queue(db: Session = Depends(get_db)):
    items = db.query(ReviewQueue).filter(ReviewQueue.status == "pending").all()
    results = []
    for item in items:
        results.append({
            "id": item.id,
            "circular_id": item.circular_id,
            "clause_id": item.clause_id,
            "previous_clause": item.previous_clause,
            "new_clause": item.new_clause,
            "highlighted_diff": item.highlighted_diff,
            "llm_explanation": item.llm_explanation,
            "confidence": item.confidence,
            "extracted_obligation": item.extracted_obligation,
            "status": item.status
        })
    return results


class ReviewActionPayload(BaseModel):
    action: str  # "approve", "reject", "edit"
    obligation_data: dict = None


@router.post("/review/{thread_id}/submit")
def submit_review_action(
    thread_id: str,
    payload: ReviewActionPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key),
):
    graph = _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    is_paused = bool(graph.get_state(config).next)

    # Try updating ReviewQueue table status if item exists
    item = None
    try:
        item = db.query(ReviewQueue).filter(ReviewQueue.id == thread_id).first()
        if item:
            item.status = "approved" if payload.action == "approve" else ("rejected" if payload.action == "reject" else "edited")
            if payload.obligation_data:
                item.extracted_obligation = payload.obligation_data
            db.commit()
    except Exception:
        pass

    if is_paused:
        # Run graph invoke in background task
        background_tasks.add_task(
            async_resume_graph, thread_id, payload.action, payload.obligation_data,
            resolve_actor(principal, None),
        )
        return {"status": "resumed_async"}

    if item:
        return {"status": "updated_db_only"}

    raise HTTPException(
        status_code=409,
        detail=f"No pending review for thread '{thread_id}' — nothing is paused.",
    )


@router.post("/review/{thread_id}/decision")
def submit_decision(
    thread_id: str,
    decision: str,
    actor: str = "reviewer",
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key),
):
    # With auth on, the audit actor is the authenticated user, not a client-supplied name.
    actor = resolve_actor(principal, actor)
    graph = _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    is_paused = bool(graph.get_state(config).next)

    if is_paused:
        try:
            item = db.query(ReviewQueue).filter(ReviewQueue.id == thread_id).first()
            if item:
                item.status = "approved" if decision.startswith("approve") else ("rejected" if decision.startswith("reject") else "edited")
                db.commit()
        except Exception:
            pass

        from langgraph.errors import GraphInterrupt
        try:
            result = graph.invoke(
                Command(resume={"decision": decision, "actor": actor}),
                config=config,
            )
        except GraphInterrupt as exc:
            state_val = graph.get_state(config).values
            return {"status": "resumed_pending", "state": state_val}
            
        return {"status": "resumed", "state": result}

    item = None
    try:
        item = db.query(ReviewQueue).filter(ReviewQueue.id == thread_id).first()
        if item:
            item.status = "approved" if decision.startswith("approve") else ("rejected" if decision.startswith("reject") else "edited")
            db.commit()
            return {"status": "updated_db_only"}
    except Exception:
        pass

    raise HTTPException(
        status_code=409,
        detail=f"No pending review for thread '{thread_id}' — nothing is paused.",
    )
