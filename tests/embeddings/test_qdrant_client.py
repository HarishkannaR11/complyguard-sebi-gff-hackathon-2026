from unittest.mock import MagicMock

from app.embeddings.qdrant_client import (
    DEFAULT_COLLECTION,
    ensure_collection,
    search,
    upsert_chunks,
)


def test_ensure_collection_creates_when_missing():
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])

    ensure_collection(client, vector_size=768)

    client.create_collection.assert_called_once()
    _, kwargs = client.create_collection.call_args
    assert kwargs["collection_name"] == DEFAULT_COLLECTION
    assert kwargs["vectors_config"].size == 768


def test_ensure_collection_skips_when_present():
    client = MagicMock()
    existing = MagicMock()
    existing.name = DEFAULT_COLLECTION
    client.get_collections.return_value = MagicMock(collections=[existing])

    ensure_collection(client)

    client.create_collection.assert_not_called()


def test_upsert_chunks_sends_one_point_per_chunk():
    client = MagicMock()
    ids = upsert_chunks(
        client,
        chunks=["clause one", "clause two"],
        vectors=[[0.1, 0.2], [0.3, 0.4]],
        metadatas=[{"source": "a.pdf"}, {"source": "a.pdf"}],
    )

    assert len(ids) == 2
    _, kwargs = client.upsert.call_args
    assert len(kwargs["points"]) == 2
    assert kwargs["points"][0].payload["text"] == "clause one"


def test_search_maps_results_to_text_and_score():
    client = MagicMock()
    hit = MagicMock(payload={"text": "clause one", "obligation_id": "obl-1"}, score=0.9)
    client.query_points.return_value = MagicMock(points=[hit])

    results = search(client, query_vector=[0.1, 0.2])

    assert results == [
        {
            "text": "clause one",
            "score": 0.9,
            "payload": {"text": "clause one", "obligation_id": "obl-1"},
        }
    ]
    client.query_points.assert_called_once_with(
        collection_name=DEFAULT_COLLECTION, query=[0.1, 0.2], limit=3
    )


# ── shared client + fallback behaviour ───────────────────────────────────────

import pytest
from unittest.mock import patch

from app.embeddings import qdrant_client as qc


@pytest.fixture(autouse=True)
def _fresh_clients():
    qc.reset_clients()
    yield
    qc.reset_clients()


def test_get_client_reuses_one_client_per_url():
    with patch.object(qc, "QdrantClient") as cls:
        cls.side_effect = lambda *a, **k: MagicMock()
        a = qc.get_client("http://qdrant.internal:6333")
        b = qc.get_client("http://qdrant.internal:6333")
        c = qc.get_client("http://other:6333")
    assert a is b
    assert a is not c
    assert cls.call_count == 2


def test_unreachable_local_server_falls_back_once_and_reports_it():
    server = MagicMock()
    server.get_collections.side_effect = RuntimeError("refused")
    embedded = MagicMock()

    def make(*args, **kwargs):
        return embedded if "path" in kwargs else server

    with patch.object(qc, "QdrantClient", side_effect=make) as cls:
        first = qc.get_client("http://localhost:6333")
        second = qc.get_client("http://localhost:6333")

    assert first is embedded and second is embedded
    assert qc.is_using_fallback()
    embedded_builds = [c for c in cls.call_args_list if "path" in c.kwargs]
    assert len(embedded_builds) == 1


def test_fallback_is_left_when_the_server_comes_back():
    down = MagicMock()
    down.get_collections.side_effect = RuntimeError("refused")
    up = MagicMock()
    embedded = MagicMock()
    state = {"server": down}

    def make(*args, **kwargs):
        return embedded if "path" in kwargs else state["server"]

    with patch.object(qc, "QdrantClient", side_effect=make), \
         patch.object(qc.time, "monotonic", side_effect=[0.0, 100.0]):
        assert qc.get_client("http://localhost:6333") is embedded
        state["server"] = up
        assert qc.get_client("http://localhost:6333") is up

    assert not qc.is_using_fallback()


def test_remote_server_gets_the_api_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("QDRANT_API_KEY", "secret-key")
    with patch.object(qc, "QdrantClient") as cls:
        qc.get_client("https://abc.cloud.qdrant.io:6333")
    cls.assert_called_once_with(url="https://abc.cloud.qdrant.io:6333", api_key="secret-key")


def test_remote_server_without_a_key_passes_none(monkeypatch):
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    with patch.object(qc, "QdrantClient") as cls:
        qc.get_client("http://qdrant.internal:6333")
    cls.assert_called_once_with(url="http://qdrant.internal:6333", api_key=None)
