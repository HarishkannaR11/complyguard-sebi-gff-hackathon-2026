import subprocess
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_importing_routes_review_module_does_not_build_the_graph():
    result = subprocess.run(
        [sys.executable, "-c", (
            "from unittest.mock import patch\n"
            "with patch('app.graph.build_graph.build_graph') as m:\n"
            "    import app.api.routes_review\n"
            "    assert not m.called, 'build_graph was called at import time'\n"
            "print('OK')"
        )],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_submit_decision_builds_graph_lazily_and_resumes_with_command():
    import app.api.routes_review as routes_review_module

    routes_review_module._graph = None
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("human_review",))
    fake_graph.invoke.return_value = {"diff_status": "amended"}

    try:
        with patch("app.api.routes_review.build_graph", return_value=fake_graph) as mock_build:
            app = FastAPI()
            app.include_router(routes_review_module.router)
            client = TestClient(app)

            response = client.post(
                "/review/circular-1:clause-1/decision",
                params={"decision": "approve", "actor": "alice"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "resumed", "state": {"diff_status": "amended"}}
        mock_build.assert_called_once()

        from langgraph.types import Command

        call_args = fake_graph.invoke.call_args
        command_arg = call_args.args[0]
        assert isinstance(command_arg, Command)
        assert command_arg.resume == {"decision": "approve", "actor": "alice"}
        assert call_args.kwargs["config"] == {
            "configurable": {"thread_id": "circular-1:clause-1"}
        }
    finally:
        routes_review_module._graph = None


def test_submit_decision_reuses_cached_graph_across_calls():
    import app.api.routes_review as routes_review_module

    routes_review_module._graph = None
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("human_review",))
    fake_graph.invoke.return_value = {}

    try:
        with patch("app.api.routes_review.build_graph", return_value=fake_graph) as mock_build:
            app = FastAPI()
            app.include_router(routes_review_module.router)
            client = TestClient(app)

            client.post("/review/t1/decision", params={"decision": "approve"})
            client.post("/review/t1/decision", params={"decision": "reject"})

        mock_build.assert_called_once()
    finally:
        routes_review_module._graph = None


def test_submit_decision_returns_409_when_thread_is_not_paused():
    import app.api.routes_review as routes_review_module

    routes_review_module._graph = None
    fake_graph = MagicMock()
    # Empty `next` means either the thread never existed, or it already ran
    # to completion — either way, there is nothing paused to resume.
    fake_graph.get_state.return_value = MagicMock(next=())

    try:
        with patch("app.api.routes_review.build_graph", return_value=fake_graph):
            app = FastAPI()
            app.include_router(routes_review_module.router)
            client = TestClient(app)

            response = client.post(
                "/review/circular-1:clause-1/decision",
                params={"decision": "approve", "actor": "alice"},
            )

        assert response.status_code == 409
        assert "no pending review" in response.json()["detail"].lower()
        fake_graph.invoke.assert_not_called()
    finally:
        routes_review_module._graph = None


def test_get_review_queue():
    import app.api.routes_review as routes_review_module
    from app.db.models import ReviewQueue
    
    app = FastAPI()
    app.include_router(routes_review_module.router)
    client = TestClient(app)
    
    mock_db = MagicMock()
    mock_item = ReviewQueue(
        id="t1",
        circular_id="c1",
        clause_id="cl1",
        previous_clause="old text",
        new_clause="new text",
        highlighted_diff="diff",
        llm_explanation="reason",
        confidence=0.9,
        extracted_obligation={"requirement": "req"},
        status="pending"
    )
    mock_db.query().filter().all.return_value = [mock_item]
    
    from app.db.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/review/queue")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == "t1"
    assert res_data[0]["status"] == "pending"


def test_submit_review_action_async():
    import app.api.routes_review as routes_review_module
    
    routes_review_module._graph = None
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("human_review",))
    
    app = FastAPI()
    app.include_router(routes_review_module.router)
    client = TestClient(app)
    
    mock_db = MagicMock()
    mock_db.query().filter().first.return_value = MagicMock()
    
    from app.db.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db
    
    with patch("app.api.routes_review.build_graph", return_value=fake_graph):
        response = client.post(
            "/review/t1/submit",
            json={"action": "approve", "obligation_data": {"requirement": "req"}}
        )
            
    assert response.status_code == 200
    assert response.json() == {"status": "resumed_async"}
    assert mock_db.commit.called
    routes_review_module._graph = None


def test_decision_actor_is_the_authenticated_user_not_the_claimed_one(monkeypatch):
    import app.api.routes_review as routes_review_module

    monkeypatch.setenv("API_KEYS", "k1:alice")
    routes_review_module._graph = None
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("human_review",))
    fake_graph.invoke.return_value = {}

    try:
        with patch("app.api.routes_review.build_graph", return_value=fake_graph):
            app = FastAPI()
            app.include_router(routes_review_module.router)
            client = TestClient(app)
            response = client.post(
                "/review/c:1/decision",
                params={"decision": "approve", "actor": "mallory"},
                headers={"X-API-Key": "k1"},
            )
        assert response.status_code == 200
        command_arg = fake_graph.invoke.call_args.args[0]
        assert command_arg.resume["actor"] == "alice"
    finally:
        routes_review_module._graph = None
