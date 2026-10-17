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


def test_health_check_reports_healthy_when_dependencies_reachable():
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        with patch("app.api.main.get_client") as mock_get_client:
            mock_get_client.return_value.get_collections.return_value = []
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "reachable", "qdrant": "reachable"}


def test_health_check_returns_503_when_qdrant_down():
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        with patch("app.api.main.get_client", side_effect=RuntimeError("no qdrant")):
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["detail"]["qdrant"].startswith("error")
    assert response.json()["detail"]["database"] == "reachable"


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


def _factory_and_override():
    factory = _make_sqlite_session_factory()

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    return factory, override


def _chunk(text, clause=None, section="General"):
    return {"text": text, "page": 1, "section": section, "clause": clause,
            "parent": None, "type": "obligation", "confidence": 0.9}


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
    with patch("app.api.main.parse_circular", return_value=[]):
        response = client.post(
            "/upload",
            files={"file": ("empty.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["clauses_processed"] == 0
    assert body["results"] == []

    _cleanup_uploaded("empty.pdf")


def test_upload_wait_processes_clauses_and_calls_supersession():
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = [
        {"diff_status": "new", "task": {"id": "task-1", "obligation_id": "obl-1", "due_date": None}},
        {"diff_status": "unchanged"},
    ]

    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()

    try:
        with (
            patch("app.api.main.parse_circular", return_value=[_chunk("1. Do X."), _chunk("2. Do Y.")]),
            patch("app.services.upload_pipeline.build_graph", return_value=fake_graph),
            patch("app.services.upload_pipeline.mark_superseded_obligations", return_value=["obl-old"]) as mock_supersede,
        ):
            response = client.post(
                "/upload?wait=true",
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

    first_state = fake_graph.invoke.call_args_list[0].args[0]
    assert first_state["circular_id"] == "demo"
    assert first_state["clause_id"] == "clause-0"
    assert first_state["raw_clause"] == "1. Do X."
    assert fake_graph.invoke.call_args_list[0].kwargs["config"] == {
        "configurable": {"thread_id": "demo:clause-0"}
    }


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

    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()

    try:
        with (
            patch("app.api.main.parse_circular", return_value=[_chunk("1. Do X quarterly.")]),
            patch("app.services.upload_pipeline.build_graph", return_value=fake_graph),
            patch("app.services.upload_pipeline.mark_superseded_obligations", return_value=[]) as mock_supersede,
        ):
            response = client.post(
                "/upload?wait=true",
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

    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()

    try:
        with (
            patch("app.api.main.parse_circular", return_value=[_chunk("1. Do X.")]),
            patch("app.services.upload_pipeline.build_graph", return_value=fake_graph),
            patch("app.services.upload_pipeline.mark_superseded_obligations") as mock_supersede,
        ):
            response = client.post(
                "/upload?wait=true",
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


def test_upload_defaults_to_background_job_that_can_be_polled():
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"diff_status": "unchanged"}
    factory, override = _factory_and_override()
    app.dependency_overrides[get_db] = override

    try:
        with (
            patch("app.api.main.SessionLocal", factory),
            patch("app.api.main.parse_circular", return_value=[_chunk("1. A."), _chunk("2. B.")]),
            patch("app.services.upload_pipeline.build_graph", return_value=fake_graph),
            patch("app.services.upload_pipeline.mark_superseded_obligations", return_value=[]),
        ):
            response = client.post(
                "/upload",
                files={"file": ("async.pdf", b"%PDF-1.4", "application/pdf")},
            )
            assert response.status_code == 202
            accepted = response.json()
            assert accepted["status"] == "accepted"
            assert accepted["clauses_total"] == 2
            assert accepted["poll_url"] == f"/jobs/{accepted['job_id']}"

            job = client.get(accepted["poll_url"]).json()
    finally:
        app.dependency_overrides.clear()
        _cleanup_uploaded("async.pdf")

    assert job["status"] == "completed"
    assert job["clauses_done"] == 2
    assert job["result"]["clauses_processed"] == 2
    assert job["error"] is None


def test_background_job_records_failure():
    factory, override = _factory_and_override()
    app.dependency_overrides[get_db] = override

    try:
        with (
            patch("app.api.main.SessionLocal", factory),
            patch("app.api.main.parse_circular", return_value=[_chunk("1. A.")]),
            patch("app.services.upload_pipeline.build_graph", side_effect=RuntimeError("no graph")),
        ):
            accepted = client.post(
                "/upload",
                files={"file": ("failjob.pdf", b"%PDF-1.4", "application/pdf")},
            ).json()
            job = client.get(accepted["poll_url"]).json()
    finally:
        app.dependency_overrides.clear()
        _cleanup_uploaded("failjob.pdf")

    assert job["status"] == "failed"
    assert "no graph" in job["error"]


def test_unknown_job_returns_404():
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        assert client.get("/jobs/does-not-exist").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_interrupted_jobs_are_failed_on_startup():
    from app.db.models import UploadJob
    from app.services.upload_jobs import fail_interrupted_jobs

    factory = _make_sqlite_session_factory()
    db = factory()
    db.add_all([UploadJob(id="j1", status="running"), UploadJob(id="j2", status="queued"),
                UploadJob(id="j3", status="completed")])
    db.commit()
    db.close()

    assert fail_interrupted_jobs(factory) == 2
    db = factory()
    assert {j.id: j.status for j in db.query(UploadJob)} == {
        "j1": "failed", "j2": "failed", "j3": "completed"}


# ── upload validation ────────────────────────────────────────────────────────

def test_upload_rejects_non_pdf_extension():
    response = client.post("/upload", files={"file": ("notes.txt", b"%PDF-1.4", "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_file_without_pdf_magic_bytes():
    response = client.post("/upload", files={"file": ("fake.pdf", b"MZ not a pdf", "application/pdf")})
    assert response.status_code == 400
    assert "valid .pdf" in response.json()["detail"]


def test_upload_rejects_empty_file():
    response = client.post("/upload", files={"file": ("empty2.pdf", b"", "application/pdf")})
    assert response.status_code == 400


def test_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")  # ~1 KB
    response = client.post(
        "/upload", files={"file": ("big.pdf", b"%PDF-1.4" + b"x" * 5000, "application/pdf")})
    assert response.status_code == 413


def test_upload_filename_cannot_escape_the_upload_directory():
    with patch("app.api.main.parse_circular", return_value=[]):
        response = client.post(
            "/upload",
            files={"file": ("../../evil.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["filename"] == "evil.pdf"
    assert not os.path.exists("evil.pdf")
    assert os.path.exists("data/raw_pdfs/evil.pdf")
    _cleanup_uploaded("evil.pdf")


def test_csv_import_rejects_non_csv_and_bad_encoding():
    assert client.post(
        "/import/obligations", files={"file": ("x.xlsx", b"a,b", "text/csv")}).status_code == 400
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        response = client.post(
            "/import/obligations", files={"file": ("x.csv", b"\xff\xfe\x00bad", "text/csv")})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


# ── auth + CORS ──────────────────────────────────────────────────────────────

def test_requests_are_open_when_no_api_keys_configured(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        assert client.get("/readiness").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_api_key_required_when_configured(monkeypatch):
    monkeypatch.setenv("API_KEYS", "s3cret:alice")
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        assert client.get("/readiness").status_code == 401
        assert client.get("/readiness", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/readiness", headers={"X-API-Key": "s3cret"}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_health_stays_public_when_auth_is_on(monkeypatch):
    monkeypatch.setenv("API_KEYS", "s3cret:alice")
    app.dependency_overrides[get_db] = _override_get_db_with_sqlite()
    try:
        with patch("app.api.main.get_client"):
            assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_cors_allows_configured_origin_only():
    ok = client.options("/readiness", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/readiness", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
