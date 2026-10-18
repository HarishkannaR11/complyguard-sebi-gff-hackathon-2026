"""Thin wrapper around the Qdrant client for storing and querying circular chunks."""
import logging
import os
import threading
import time
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "circular_clauses"


FALLBACK_PATH = "./qdrant_db"
FALLBACK_RETRY_SECONDS = 30.0

_lock = threading.Lock()
_clients: dict[str, QdrantClient] = {}
_fallback: QdrantClient | None = None
_fallback_since = 0.0


def reset_clients() -> None:
    """Drop cached clients (used by tests)."""
    global _fallback, _fallback_since
    with _lock:
        _clients.clear()
        _fallback = None
        _fallback_since = 0.0


def is_using_fallback() -> bool:
    """True when the configured Qdrant server was unreachable and the local file store is in use."""
    return _fallback is not None


def get_client(url: str | None = None) -> QdrantClient:
    """Return a shared client for the configured Qdrant.

    One client per URL is created and reused. For a local URL that cannot be reached,
    fall back to an embedded on-disk store (so the demo runs without Docker) -- loudly,
    and re-probing the real server every FALLBACK_RETRY_SECONDS.
    """
    global _fallback, _fallback_since
    q_url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
    is_local_server = q_url.startswith(("http://localhost", "http://127.0.0.1"))

    with _lock:
        cached = _clients.get(q_url)
        if cached is not None:
            return cached

        if is_local_server:
            if _fallback is not None and time.monotonic() - _fallback_since < FALLBACK_RETRY_SECONDS:
                return _fallback
            try:
                client = QdrantClient(url=q_url, timeout=2.0)
                client.get_collections()
            except Exception:
                if _fallback is None:
                    logger.error(
                        "Qdrant at %s is unreachable; FALLING BACK to a local embedded store at %s. "
                        "Data written now will not be in the real Qdrant.", q_url, FALLBACK_PATH,
                    )
                    _fallback = QdrantClient(path=FALLBACK_PATH)
                _fallback_since = time.monotonic()
                return _fallback
            if _fallback is not None:
                logger.warning("Qdrant at %s is reachable again; leaving the local fallback store.", q_url)
                _fallback.close()
                _fallback = None
            _clients[q_url] = client
            return client

        if q_url == ":memory:":
            client = QdrantClient(location=":memory:")
        elif q_url.startswith(("/", "./")):
            client = QdrantClient(path=q_url)
        else:
            # A remote server (e.g. Qdrant Cloud) normally requires an API key.
            client = QdrantClient(url=q_url, api_key=os.environ.get("QDRANT_API_KEY") or None)
        _clients[q_url] = client
        return client


def ensure_collection(
    client: QdrantClient,
    collection_name: str = DEFAULT_COLLECTION,
    vector_size: int = 768,
) -> None:
    existing = [c.name for c in client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def upsert_chunks(
    client: QdrantClient,
    chunks: list[str],
    vectors: list[list[float]],
    metadatas: list[dict],
    collection_name: str = DEFAULT_COLLECTION,
) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in chunks]
    points = [
        PointStruct(id=ids[i], vector=vectors[i], payload={**metadatas[i], "text": chunks[i]})
        for i in range(len(chunks))
    ]
    client.upsert(collection_name=collection_name, points=points)
    return ids


def search(
    client: QdrantClient,
    query_vector: list[float],
    limit: int = 3,
    collection_name: str = DEFAULT_COLLECTION,
) -> list[dict]:
    response = client.query_points(
        collection_name=collection_name, query=query_vector, limit=limit
    )
    return [
        {"text": p.payload.get("text"), "score": p.score, "payload": p.payload}
        for p in response.points
    ]


def find_by_obligation_id(
    client: QdrantClient,
    obligation_id: str,
    collection_name: str = DEFAULT_COLLECTION,
) -> dict | None:
    """Look up the source clause a mapped obligation was extracted from, for traceability."""
    points, _ = client.scroll(
        collection_name=collection_name,
        scroll_filter=Filter(
            must=[FieldCondition(key="obligation_id", match=MatchValue(value=obligation_id))]
        ),
        limit=1,
    )
    if not points:
        return None
    return points[0].payload
