"""
gap_engine.py

Compares regulatory obligations (extracted from SEBI circulars) against company
obligations (imported from CSV) to produce structured gap results.

Rules:
- Never executes if company_obligations table is empty.
- Returns HTTP 400 via FastAPIHTTPException if called with no company data.
- Identifies: missing, extra, met, overdue gaps.
"""
from datetime import date
from fastapi import HTTPException


def compute_status(has_evidence: bool, deadline: str | None, today: date) -> str:
    if has_evidence:
        return "met"
    if deadline and date.fromisoformat(deadline) < today:
        return "overdue"
    return "pending"


def update_all_task_statuses(db) -> None:
    """Recompute status for every Task, based on its EvidenceLog rows and due_date."""
    from app.db.models import EvidenceLog, Task

    today = date.today()
    for task in db.query(Task).all():
        if task.status == "met":
            continue
        has_evidence = (
            db.query(EvidenceLog).filter(EvidenceLog.task_id == task.id).first()
            is not None
        )
        deadline = task.due_date.date().isoformat() if task.due_date else None
        task.status = compute_status(has_evidence, deadline, today)
    db.commit()


def get_gaps(db) -> list:
    """Legacy shim: still returns overdue/pending Tasks for backwards-compat."""
    from app.db.models import Task

    update_all_task_statuses(db)
    return db.query(Task).filter(Task.status.in_(["pending", "overdue"])).all()


def has_company_obligations(db) -> bool:
    """Return True if at least one CompanyObligation row exists."""
    from app.db.models import CompanyObligation
    return db.query(CompanyObligation).first() is not None


def run_gap_analysis(db) -> dict:
    """
    Full gap analysis comparing regulatory obligations against company obligations.

    Returns a structured summary:
    {
        "regulatory_count": int,
        "company_count": int,
        "missing": [...],     # regulatory obligations with no company match
        "extra": [...],       # company obligations with no regulatory match
        "met": [...],         # matched and fulfilled obligations
        "overdue": [...],     # matched but past due
        "compliance_score": float,  # 0.0 – 100.0
    }

    Raises HTTP 400 if no company obligations exist.
    """
    from app.db.models import Obligation, CompanyObligation, SOURCE_REGULATORY
    import difflib

    if not has_company_obligations(db):
        raise HTTPException(
            status_code=400,
            detail="Company obligations have not been uploaded. Please import your company obligations CSV before running gap analysis."
        )

    regulatory = db.query(Obligation).filter(
        Obligation.status == "active",
        Obligation.source_type == SOURCE_REGULATORY
    ).all()

    company = db.query(CompanyObligation).filter(
        CompanyObligation.status.in_(["open", "met"])
    ).all()

    if not regulatory:
        return {
            "regulatory_count": 0,
            "company_count": len(company),
            "missing": [],
            "extra": [_co_to_dict(c) for c in company],
            "met": [],
            "overdue": [],
            "compliance_score": 0.0,
        }

    # Simple text-similarity matching (≥70% similarity = match)
    THRESHOLD = 0.70
    today = date.today()

    matched_reg_ids = set()
    matched_co_ids = set()
    met_items = []
    overdue_items = []

    for reg in regulatory:
        reg_text = (reg.requirement or "").lower()
        best_score = 0.0
        best_co = None
        for co in company:
            co_text = (co.requirement or "").lower()
            score = difflib.SequenceMatcher(None, reg_text, co_text).ratio()
            if score > best_score:
                best_score = score
                best_co = co

        if best_co and best_score >= THRESHOLD:
            matched_reg_ids.add(reg.id)
            matched_co_ids.add(best_co.id)
            is_met = best_co.status == "met"
            is_overdue = (
                not is_met
                and best_co.due_date
                and best_co.due_date.date() < today
            )
            item = {
                "regulatory_id": reg.id,
                "company_id": best_co.id,
                "requirement": reg.requirement,
                "company_requirement": best_co.requirement,
                "match_score": round(best_score * 100),
                "due_date": best_co.due_date.date().isoformat() if best_co.due_date else None,
                "status": "met" if is_met else ("overdue" if is_overdue else "pending"),
            }
            if is_met:
                met_items.append(item)
            elif is_overdue:
                overdue_items.append(item)
            else:
                met_items.append(item)  # pending but matched – counts as covered

    missing = [
        {"regulatory_id": r.id, "requirement": r.requirement, "frequency": r.frequency}
        for r in regulatory if r.id not in matched_reg_ids
    ]
    extra = [
        _co_to_dict(c)
        for c in company if c.id not in matched_co_ids
    ]

    total = len(regulatory)
    fulfilled = len(met_items)  # matched obligations (any non-missing)
    compliance_score = round((fulfilled / total) * 100, 1) if total > 0 else 0.0

    return {
        "regulatory_count": len(regulatory),
        "company_count": len(company),
        "missing": missing,
        "extra": extra,
        "met": met_items,
        "overdue": overdue_items,
        "compliance_score": compliance_score,
    }


def _co_to_dict(co) -> dict:
    return {
        "company_id": co.id,
        "requirement": co.requirement,
        "frequency": co.frequency,
        "due_date": co.due_date.date().isoformat() if co.due_date else None,
        "status": co.status,
    }
