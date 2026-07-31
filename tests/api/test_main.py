import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.db.database import Base, get_db
from app.db.models import Obligation, Task

client = TestClient(app)


def _make_sqlite_session_factory():
    # FastAPI runs sync route handlers (like these) in a worker thread, not
    # the thread that seeds test data — plain sqlite:///:memory: gives each
    # thread its own private, empty database (SingletonThreadPool), so a
    # session opened during the request would see "no such table" even
    # though the test just seeded rows moments earlier. StaticPool +
    # check_same_thread=False shares the one real in-memory connection
    # across threads instead.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _override_get_db_with_sqlite():
    TestSessionLocal = _make_sqlite_session_factory()

    def override():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    return override


def _cleanup_uploaded(filename: str):
    created = f"data/raw_pdfs/{filename}"
    if os.path.exists(created):
        try:
            os.remove(created)
        except PermissionError:
            pass


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_gaps_returns_real_tasks_from_the_database():
    # /gaps now returns 400 when no company obligations are uploaded (new workflow).
    # Use /gaps/legacy which still returns Task-based gaps for backward compat.
    TestSessionLocal = _make_sqlite_session_factory()

    seed_db = TestSessionLocal()
    seed_db.add(Obligation(id="obl-1", clause_id="c1", requirement="Do X",
                            frequency="annual", evidence_type="policy",
                            deadline_rule="annual"))
    seed_db.add(Task(id="task-1", obligation_id="obl-1", owner="compliance",
                      due_date=datetime(2020, 1, 1), status="open"))
    seed_db.commit()
    seed_db.close()

    def override():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        response = client.get("/gaps/legacy")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "task-1"
    assert body[0]["status"] == "overdue"


def test_upload_returns_422_for_an_unreadable_pdf():
    pdf_bytes = b"%PDF-1.4 minimal"  # not a real PDF, PyMuPDF can't parse it
    response = client.post(
        "/upload",
        files={"file": ("test_upload_scaffold.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 422
    assert "PDF cleaning failed" in response.json()["detail"]

    _cleanup_uploaded("test_upload_scaffold.pdf")


def test_upload_returns_zero_clauses_when_none_found():
    with patch("app.api.main.extract_and_clean", return_value="   \n\n  "):
        response = client.post(
            "/upload",
            files={"file": ("empty.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["clauses_processed"] == 0
    assert body["results"] == []

    _cleanup_uploaded("empty.pdf")


def test_upload_processes_clauses_and_calls_supersession():
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = [
        {"diff_status": "new", "task": {"id": "task-1", "obligation_id": "obl-1", "due_date": None}},
        {"diff_status": "unchanged"},
    ]

    override_get_db = _override_get_db_with_sqlite()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with (
            patch("app.api.main.extract_and_clean", return_value="1. Do X.\n\n2. Do Y."),
            patch("app.api.main.build_graph", return_value=fake_graph),
            patch("app.api.main.mark_superseded_obligations", return_value=["obl-old"]) as mock_supersede,
        ):
            response = client.post(
                "/upload",
                files={"file": ("demo.pdf", b"%PDF-1.4", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup_uploaded("demo.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["circular_id"] == "demo"
    assert body["clauses_processed"] == 2
    assert body["results"][0] == {
        "clause_id": "clause-0",
        "status": "processed",
        "diff_status": "new",
        "task": {"id": "task-1", "obligation_id": "obl-1", "due_date": None},
    }
    assert body["results"][1]["status"] == "processed"
    assert body["superseded_obligation_ids"] == ["obl-old"]
    assert body["supersession_skipped_due_to_errors"] is False

    mock_supersede.assert_called_once()
    args, _ = mock_supersede.call_args
    assert args[1] == "demo"
    assert args[2] == {"obl-1"}

    fake_graph.invoke.assert_any_call(
        {
            "circular_id": "demo",
            "clause_id": "clause-0",
            "raw_clause": "1. Do X.",
            "heading": None,
        },
        config={"configurable": {"thread_id": "demo:clause-0"}},
    )


def test_upload_marks_pending_review_and_protects_its_obligation_from_supersession():
    class FakeInterrupt:
        def __init__(self, value):
            self.value = value

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {
        "__interrupt__": [
            FakeInterrupt({
                "similarity_match": {"payload": {"obligation_id": "obl-2"}},
            })
        ]
    }

    override_get_db = _override_get_db_with_sqlite()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with (
            patch("app.api.main.extract_and_clean", return_value="1. Do X quarterly."),
            patch("app.api.main.build_graph", return_value=fake_graph),
            patch("app.api.main.mark_superseded_obligations", return_value=[]) as mock_supersede,
        ):
            response = client.post(
                "/upload",
                files={"file": ("amend.pdf", b"%PDF-1.4", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup_uploaded("amend.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"clause_id": "clause-0", "status": "pending_review"}]

    mock_supersede.assert_called_once()
    args, _ = mock_supersede.call_args
    assert args[2] == {"obl-2"}


def test_upload_skips_supersession_when_a_clause_errors():
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = RuntimeError("groq is down")

    override_get_db = _override_get_db_with_sqlite()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with (
            patch("app.api.main.extract_and_clean", return_value="1. Do X."),
            patch("app.api.main.build_graph", return_value=fake_graph),
            patch("app.api.main.mark_superseded_obligations") as mock_supersede,
        ):
            response = client.post(
                "/upload",
                files={"file": ("broken.pdf", b"%PDF-1.4", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup_uploaded("broken.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [
        {"clause_id": "clause-0", "status": "error", "detail": "groq is down"}
    ]
    assert body["supersession_skipped_due_to_errors"] is True
    assert body["superseded_obligation_ids"] == []
    mock_supersede.assert_not_called()
