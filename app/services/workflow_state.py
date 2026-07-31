"""
Centralized Workflow State Manager for RegOps AI.

States:
  IDLE                   – fresh install, nothing uploaded
  DOCUMENT_UPLOADED      – PDF saved to disk, parsing starting
  EXTRACTION_RUNNING     – pipeline in progress
  REVIEW_PENDING         – ≥1 clause requires human review
  REVIEW_APPROVED        – all pending reviews resolved
  REGULATORY_COMPLETE    – user clicked "Finish" (regulatory baseline saved)
  COMPANY_DATA_IMPORTED  – company CSV successfully imported
  GAP_ANALYSIS_COMPLETE  – gap engine has run at least once
  DASHBOARD_READY        – gap data available for the compliance dashboard
"""
from enum import Enum


class WorkflowState(str, Enum):
    IDLE                  = "IDLE"
    DOCUMENT_UPLOADED     = "DOCUMENT_UPLOADED"
    EXTRACTION_RUNNING    = "EXTRACTION_RUNNING"
    REVIEW_PENDING        = "REVIEW_PENDING"
    REVIEW_APPROVED       = "REVIEW_APPROVED"
    REGULATORY_COMPLETE   = "REGULATORY_COMPLETE"
    COMPANY_DATA_IMPORTED = "COMPANY_DATA_IMPORTED"
    GAP_ANALYSIS_COMPLETE = "GAP_ANALYSIS_COMPLETE"
    DASHBOARD_READY       = "DASHBOARD_READY"


# Persistence – a tiny SQLite/Postgres table stores the current state.
# We use a singleton row with id='current'.

_current_state: WorkflowState = WorkflowState.IDLE


def get_state(db=None) -> WorkflowState:
    """Return persisted workflow state from DB, or in-process fallback."""
    global _current_state
    if db is None:
        return _current_state
    try:
        from app.db.models import WorkflowStateRecord
        row = db.query(WorkflowStateRecord).filter(WorkflowStateRecord.id == "current").first()
        if row:
            _current_state = WorkflowState(row.state)
            return _current_state
    except Exception:
        pass
    return _current_state


def set_state(new_state: WorkflowState, db=None) -> WorkflowState:
    """Persist new workflow state."""
    global _current_state
    _current_state = new_state
    if db is None:
        return _current_state
    try:
        from app.db.models import WorkflowStateRecord
        row = db.query(WorkflowStateRecord).filter(WorkflowStateRecord.id == "current").first()
        if row:
            row.state = new_state.value
        else:
            row = WorkflowStateRecord(id="current", state=new_state.value)
            db.add(row)
        db.commit()
    except Exception:
        db.rollback()
    return _current_state


def advance(new_state: WorkflowState, db=None) -> WorkflowState:
    """Only advance if new_state is logically later than current state."""
    ORDER = list(WorkflowState)
    current = get_state(db)
    if ORDER.index(new_state) > ORDER.index(current):
        return set_state(new_state, db)
    return current
