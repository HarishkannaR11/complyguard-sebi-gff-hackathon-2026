from langgraph.checkpoint.memory import MemorySaver

from app.graph.build_graph import build_graph, route_after_diff, route_after_evidence


def test_build_graph_compiles_with_injected_checkpointer():
    graph = build_graph(checkpointer=MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    assert {
        "chunker", "embedder", "extractor", "differ", "human_review",
        "mapper", "evidence_check", "gap_engine", "finalize",
    } <= node_names


def test_route_after_diff_sends_amended_and_superseded_to_human_review():
    assert route_after_diff({"diff_status": "amended"}) == "human_review"
    assert route_after_diff({"diff_status": "superseded"}) == "human_review"


def test_route_after_diff_sends_unchanged_to_finalize():
    assert route_after_diff({"diff_status": "unchanged"}) == "finalize"


def test_route_after_diff_sends_new_to_mapper():
    assert route_after_diff({"diff_status": "new"}) == "mapper"


def test_route_after_evidence_routing():
    assert route_after_evidence({"evidence_status": "missing"}) == "gap_engine"
    assert route_after_evidence({"evidence_status": "invalid"}) == "human_review"
    assert route_after_evidence({"evidence_status": "present"}) == "finalize"


def test_checkpointer_failure_raises_unless_fallback_allowed(monkeypatch):
    import pytest
    from app.graph import build_graph as bg

    monkeypatch.setattr(bg, "_checkpointer", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:1/none")
    monkeypatch.delenv("ALLOW_MEMORY_CHECKPOINTER", raising=False)

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(bg.PostgresSaver, "from_conn_string", boom)
    with pytest.raises(RuntimeError):
        bg._get_checkpointer()

    monkeypatch.setenv("ALLOW_MEMORY_CHECKPOINTER", "1")
    assert isinstance(bg._get_checkpointer(), MemorySaver)
    monkeypatch.setattr(bg, "_checkpointer", None)


def test_route_after_diff_low_confidence_goes_to_review():
    assert route_after_diff({"diff_status": "new", "overall_confidence": 0.5}) == "human_review"
    assert route_after_diff({"diff_status": "new", "confidence": 0.6}) == "human_review"
    assert route_after_diff({"diff_status": "new", "validation_status": "failed"}) == "human_review"


def test_route_after_diff_tolerates_none_confidence():
    state = {"diff_status": "new", "overall_confidence": None, "confidence": None}
    assert route_after_diff(state) == "mapper"
