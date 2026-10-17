import json
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AuditTrail, EvidenceLog, Obligation, Task
from app.graph.nodes import (
    evidence_node,
    finalize_node,
    gap_engine_node,
    human_review_node,
    mapper_node,
)


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr("app.graph.nodes.SessionLocal", TestSessionLocal)
    session = TestSessionLocal()
    yield session
    session.close()


def test_mapper_node_creates_new_obligation_and_task(db_session):
    state = {
        "circular_id": "circular-1",
        "clause_id": "clause-1",
        "raw_clause": "1. Appoint a compliance officer.",
        "embedding": [0.1, 0.2],
        "diff_status": "new",
        "similarity_match": None,
        "extracted_obligation": {
            "requirement": "Appoint a compliance officer",
            "frequency": "one-time",
            "evidence_type": "board resolution",
            "deadline_rule": "2026-06-30",
        },
    }

    with patch("app.graph.nodes.get_client", return_value="fake-client"), \
         patch("app.graph.nodes.upsert_chunks") as mock_upsert:
        result = mapper_node(state)

    obligation = db_session.query(Obligation).one()
    assert obligation.requirement == "Appoint a compliance officer"
    task = db_session.query(Task).one()
    assert task.obligation_id == obligation.id
    assert task.due_date == datetime(2026, 6, 30)
    assert result["task"]["id"] == task.id
    assert result["task"]["obligation_id"] == obligation.id
    mock_upsert.assert_called_once()
    _, kwargs = mock_upsert.call_args
    assert kwargs["metadatas"][0]["obligation_id"] == obligation.id


def test_mapper_node_updates_existing_obligation_when_amended(db_session):
    db_session.add(Obligation(id="obl-1", clause_id="clause-0", requirement="Old text",
                               frequency="annual", evidence_type="policy",
                               deadline_rule="annual"))
    db_session.commit()

    state = {
        "circular_id": "circular-1",
        "clause_id": "clause-1",
        "raw_clause": "1. Do X quarterly.",
        "embedding": [0.1, 0.2],
        "diff_status": "amended",
        "similarity_match": {"payload": {"obligation_id": "obl-1"}},
        "extracted_obligation": {
            "requirement": "Do X",
            "frequency": "quarterly",
            "evidence_type": "policy doc",
            "deadline_rule": "quarterly",
        },
    }

    with patch("app.graph.nodes.get_client", return_value="fake-client"), \
         patch("app.graph.nodes.upsert_chunks"):
        mapper_node(state)

    assert db_session.query(Obligation).count() == 1
    obligation = db_session.query(Obligation).one()
    assert obligation.id == "obl-1"
    assert obligation.requirement == "Do X"


def test_mapper_node_skips_when_rejected(db_session):
    state = {"human_decision": "reject", "diff_status": "amended"}
    result = mapper_node(state)
    assert result == {}
    assert db_session.query(Obligation).count() == 0


def test_mapper_node_skips_when_unchanged(db_session):
    state = {"diff_status": "unchanged"}
    result = mapper_node(state)
    assert result == {}
    assert db_session.query(Task).count() == 0


def test_evidence_node_reports_present_when_evidence_exists(db_session):
    db_session.add(Obligation(id="obl-1", clause_id="c1", requirement="X",
                               frequency="annual", evidence_type="policy",
                               deadline_rule="annual"))
    db_session.add(Task(id="task-1", obligation_id="obl-1", owner="compliance"))
    db_session.add(EvidenceLog(id="ev-1", task_id="task-1", file_ref="doc.pdf"))
    db_session.commit()

    result = evidence_node({"task": {"id": "task-1"}})

    assert result == {"evidence_status": "present"}


def test_evidence_node_reports_missing_when_no_evidence(db_session):
    db_session.add(Obligation(id="obl-2", clause_id="c2", requirement="Y",
                               frequency="annual", evidence_type="policy",
                               deadline_rule="annual"))
    db_session.add(Task(id="task-2", obligation_id="obl-2", owner="compliance"))
    db_session.commit()

    result = evidence_node({"task": {"id": "task-2"}})

    assert result == {"evidence_status": "missing"}


def test_evidence_node_reports_missing_when_no_task_in_state():
    assert evidence_node({}) == {"evidence_status": "missing"}


def test_gap_engine_node_marks_overdue_task(db_session):
    db_session.add(Obligation(id="obl-3", clause_id="c3", requirement="Z",
                               frequency="annual", evidence_type="policy",
                               deadline_rule="annual"))
    db_session.add(Task(id="task-3", obligation_id="obl-3", owner="compliance",
                         due_date=datetime(2020, 1, 1), status="open"))
    db_session.commit()

    result = gap_engine_node({"task": {"id": "task-3"}})

    assert result["task"]["status"] == "overdue"
    task = db_session.query(Task).filter(Task.id == "task-3").one()
    assert task.status == "overdue"


def test_gap_engine_node_noop_without_task():
    assert gap_engine_node({}) == {}


def test_human_review_node_approve_writes_audit_entry(db_session):
    with patch("app.graph.nodes.interrupt", return_value={"decision": "approve", "actor": "alice"}):
        result = human_review_node({
            "circular_id": "circular-1",
            "clause_id": "clause-1",
            "extracted_obligation": {"requirement": "Do X"},
            "diff_status": "amended",
            "similarity_match": None,
        })

    assert result["human_decision"] == "approve"
    assert result["extracted_obligation"] == {"requirement": "Do X"}
    entry = db_session.query(AuditTrail).one()
    assert entry.actor == "alice"
    assert entry.node_name == "human_review"
    assert json.loads(entry.action) if isinstance(entry.action, str) else entry.action


def test_human_review_node_amend_merges_correction(db_session):
    with patch("app.graph.nodes.interrupt", return_value={
        "decision": 'amend:{"requirement": "Corrected text"}', "actor": "bob",
    }):
        result = human_review_node({
            "circular_id": "circular-1",
            "clause_id": "clause-1",
            "extracted_obligation": {"requirement": "Do X", "frequency": "annual"},
            "diff_status": "amended",
            "similarity_match": None,
        })

    assert result["human_decision"] == "amend"
    assert result["extracted_obligation"] == {
        "requirement": "Corrected text", "frequency": "annual",
    }


def test_finalize_node_writes_hash_chained_audit_entry(db_session):
    result_1 = finalize_node({
        "circular_id": "circular-1", "clause_id": "clause-1",
        "task": {"id": "task-1", "obligation_id": "obl-1"},
        "diff_status": "new", "human_decision": None,
    })
    result_2 = finalize_node({
        "circular_id": "circular-1", "clause_id": "clause-2",
        "task": {"id": "task-2", "obligation_id": "obl-2"},
        "diff_status": "new", "human_decision": None,
    })

    assert result_1 == {}
    assert result_2 == {}
    entries = db_session.query(AuditTrail).order_by(AuditTrail.timestamp).all()
    assert len(entries) == 2
    assert entries[0].prev_hash == ""
    assert entries[1].prev_hash == entries[0].hash
    assert entries[0].actor == "system"


def test_mapper_logs_a_repair_hint_and_reraises_when_qdrant_write_fails(db_session, caplog):
    import logging

    state = {
        "circular_id": "c1", "clause_id": "clause-0", "raw_clause": "1. Do X.",
        "embedding": [0.1, 0.2], "diff_status": "new", "similarity_match": None,
        "extracted_obligation": {"requirement": "Do X", "frequency": "annual",
                                 "evidence_type": "policy", "deadline_rule": "annual"},
    }
    with patch("app.graph.nodes.get_client", return_value="fake-client"), \
         patch("app.graph.nodes.upsert_chunks", side_effect=RuntimeError("qdrant down")), \
         caplog.at_level(logging.ERROR, logger="app.graph.nodes"):
        with pytest.raises(RuntimeError, match="qdrant down"):
            mapper_node(state)
    assert "reconcile-vectors" in caplog.text
    assert db_session.query(Obligation).count() == 1  # the row is committed; reconcile repairs the vector


def test_human_review_node_records_where_the_clause_came_from(db_session):
    from app.db.models import ReviewQueue

    with patch("app.graph.nodes.interrupt", return_value={"decision": "approve", "actor": "a"}):
        human_review_node({
            "circular_id": "circ", "clause_id": "clause-4", "raw_clause": "x",
            "extracted_obligation": {"requirement": "r"}, "diff_status": "amended",
            "similarity_match": None, "clause_uuid": "cu-1", "clause_num": "4.2",
            "section": "Risk Management", "page": 7,
        })
    item = db_session.get(ReviewQueue, "circ:clause-4")
    assert (item.clause_uuid, item.clause_number, item.section, item.page) == ("cu-1", "4.2", "Risk Management", 7)


def test_generate_text_diff_escapes_html_from_the_pdf():
    from app.graph.nodes import generate_text_diff

    hostile = 'pay <img src=x onerror=alert(1)> now & <script>steal()</script>'
    for old in ("", "pay now"):
        out = generate_text_diff(old, hostile)
        assert "<img" not in out and "<script" not in out
        assert "&lt;img" in out and "&amp;" in out

    # the diff's own markup is still produced
    out = generate_text_diff("pay now", "pay later")
    assert "<del" in out and "<ins" in out
