"""Human-review API routes: resume a paused compliance-pipeline run with a decision."""
from fastapi import APIRouter, HTTPException
from langgraph.types import Command

from app.graph.build_graph import build_graph

router = APIRouter()

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@router.post("/review/{thread_id}/decision")
def submit_decision(thread_id: str, decision: str, actor: str = "reviewer"):
    graph = _get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    # Command(resume=...) is a silent no-op on a thread that isn't actually
    # paused (never existed, or already ran to completion) — it just returns
    # the last checkpointed state without doing anything, which looks like a
    # normal success response even though the "decision" was never applied to
    # anything. Reject that case explicitly instead of returning a
    # misleading 200.
    if not graph.get_state(config).next:
        raise HTTPException(
            status_code=409,
            detail=f"No pending review for thread '{thread_id}' — nothing is paused.",
        )

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
