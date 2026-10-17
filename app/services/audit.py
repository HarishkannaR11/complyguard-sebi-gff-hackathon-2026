"""Tamper-evident audit-trail hashing and chain verification."""
import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AuditTrail


def compute_audit_hash(prev_hash: str, action: dict, timestamp: datetime) -> str:
    payload = prev_hash + json.dumps(action, sort_keys=True) + timestamp.isoformat()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_chain(db: Session) -> dict:
    """Re-walk the whole audit chain and report the first break, if any.

    The chain is followed through ``prev_hash`` links (the genesis row has
    ``prev_hash == ""``), not through timestamps, so rows that share a
    timestamp cannot be mis-ordered.
    """
    rows = db.query(AuditTrail).all()
    total = len(rows)
    if total == 0:
        return {"valid": True, "total": 0, "verified": 0, "broken_at": None, "reason": None}

    by_prev: dict[str, list[AuditTrail]] = {}
    for row in rows:
        by_prev.setdefault(row.prev_hash or "", []).append(row)

    verified = 0
    prev_hash = ""
    seen: set[str] = set()
    while True:
        children = by_prev.get(prev_hash, [])
        if not children:
            break
        if len(children) > 1:
            return _broken(total, verified, children[0].id, "fork: multiple entries share the same prev_hash")
        row = children[0]
        if row.id in seen:
            return _broken(total, verified, row.id, "cycle detected in chain")
        seen.add(row.id)
        expected = compute_audit_hash(row.prev_hash or "", row.action, row.timestamp)
        if expected != row.hash:
            return _broken(total, verified, row.id, "hash mismatch: entry was modified")
        verified += 1
        prev_hash = row.hash

    if verified != total:
        orphan = next(r for r in rows if r.id not in seen)
        return _broken(total, verified, orphan.id, "entry is not reachable from the genesis row")
    return {"valid": True, "total": total, "verified": verified, "broken_at": None, "reason": None}


def _broken(total: int, verified: int, entry_id: str, reason: str) -> dict:
    return {"valid": False, "total": total, "verified": verified, "broken_at": entry_id, "reason": reason}
