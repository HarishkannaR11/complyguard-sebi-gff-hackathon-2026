"""
routes_workflow.py

Workflow state management API endpoints.

GET  /workflow-state        – returns current state + capability flags
POST /workflow-state        – set an explicit state (body: {"state": "REGULATORY_COMPLETE"})
POST /workflow/finish       – user clicks "Finish" → REGULATORY_COMPLETE
POST /workflow/start-compliance – user clicks "Continue to Compliance" (kept at REGULATORY_COMPLETE, CSV upload unlocks next)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.workflow_state import WorkflowState, get_state, set_state, advance

router = APIRouter(tags=["workflow"])


# ─── helper ──────────────────────────────────────────────────────────────────
def _capability_flags(state: WorkflowState) -> dict:
    ORDER = list(WorkflowState)
    rank = ORDER.index(state)

    def ge(s: WorkflowState) -> bool:
        return rank >= ORDER.index(s)

    return {
        "state": state.value,
        # Workflow 1 – Regulatory Intelligence
        "can_upload":          True,
        "can_review":          ge(WorkflowState.REVIEW_PENDING),
        "can_approve":         ge(WorkflowState.REVIEW_PENDING),
        "regulatory_complete": ge(WorkflowState.REGULATORY_COMPLETE),
        # Workflow 2 – Compliance Management
        "can_upload_csv":      ge(WorkflowState.REGULATORY_COMPLETE),
        "can_run_gap":         ge(WorkflowState.COMPANY_DATA_IMPORTED),
        "dashboard_ready":     ge(WorkflowState.DASHBOARD_READY),
        # Friendly display
        "has_regulatory_obligations": ge(WorkflowState.REVIEW_APPROVED),
        "has_company_obligations":    ge(WorkflowState.COMPANY_DATA_IMPORTED),
        "gap_analysis_available":     ge(WorkflowState.DASHBOARD_READY),
    }


# ─── endpoints ───────────────────────────────────────────────────────────────
@router.get("/workflow-state")
def get_workflow_state(db: Session = Depends(get_db)):
    state = get_state(db)
    return _capability_flags(state)


class StateUpdate(BaseModel):
    state: str


@router.post("/workflow-state")
def update_workflow_state(body: StateUpdate, db: Session = Depends(get_db)):
    try:
        new_state = WorkflowState(body.state)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown state: {body.state}. Valid values: {[s.value for s in WorkflowState]}")
    set_state(new_state, db)
    return _capability_flags(new_state)


@router.post("/workflow/finish")
def workflow_finish(db: Session = Depends(get_db)):
    """User chose 'Finish' — regulatory baseline is complete."""
    state = advance(WorkflowState.REGULATORY_COMPLETE, db)
    return {"status": "regulatory_complete", **_capability_flags(state)}


@router.post("/workflow/start-compliance")
def workflow_start_compliance(db: Session = Depends(get_db)):
    """User chose 'Continue to Compliance Analysis' — stay at REGULATORY_COMPLETE, unlock CSV upload."""
    state = get_state(db)
    # Already at or beyond REGULATORY_COMPLETE — just confirm
    if list(WorkflowState).index(state) >= list(WorkflowState).index(WorkflowState.REGULATORY_COMPLETE):
        return {"status": "compliance_unlocked", **_capability_flags(state)}
    # Force to REGULATORY_COMPLETE so CSV upload becomes available
    state = set_state(WorkflowState.REGULATORY_COMPLETE, db)
    return {"status": "compliance_unlocked", **_capability_flags(state)}
