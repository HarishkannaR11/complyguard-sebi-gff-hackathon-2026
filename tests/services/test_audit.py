from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AuditTrail
from app.services.audit import compute_audit_hash, verify_chain


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _append(db, n, prev_hash, ts=None):
    ts = ts or datetime(2026, 1, 1) + timedelta(seconds=n)
    action = {"n": n}
    row = AuditTrail(
        id=f"a{n}", thread_id="t", node_name="finalize", action=action, actor="system",
        timestamp=ts, prev_hash=prev_hash, hash=compute_audit_hash(prev_hash, action, ts),
    )
    db.add(row)
    db.commit()
    return row


def _chain(db, length):
    prev = ""
    for n in range(length):
        prev = _append(db, n, prev).hash


def test_empty_chain_is_valid():
    assert verify_chain(_db())["valid"] is True


def test_intact_chain_is_valid_even_with_identical_timestamps():
    db = _db()
    ts = datetime(2026, 1, 1)
    prev = ""
    for n in range(4):
        prev = _append(db, n, prev, ts).hash
    result = verify_chain(db)
    assert result == {"valid": True, "total": 4, "verified": 4, "broken_at": None, "reason": None}


def test_modified_entry_is_detected():
    db = _db()
    _chain(db, 3)
    row = db.get(AuditTrail, "a1")
    row.action = {"n": 999}
    db.commit()
    result = verify_chain(db)
    assert result["valid"] is False
    assert result["broken_at"] == "a1"
    assert result["verified"] == 1


def test_deleted_entry_is_detected():
    db = _db()
    _chain(db, 3)
    db.delete(db.get(AuditTrail, "a1"))
    db.commit()
    result = verify_chain(db)
    assert result["valid"] is False
    assert result["broken_at"] == "a2"


def test_fork_is_detected():
    db = _db()
    _chain(db, 2)
    _append(db, 50, db.get(AuditTrail, "a0").hash)
    result = verify_chain(db)
    assert result["valid"] is False
    assert "fork" in result["reason"]
