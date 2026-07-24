"""Thin wrapper around the Qdrant client for storing and querying circular chunks."""
import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

DEFAULT_COLLECTION = "circular_clauses"


def get_client(url: str | None = None) -> QdrantClient:
    q_url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
    if q_url.startswith("http://localhost") or q_url.startswith("http://127.0.0.1") or not q_url:
        try:
            client = QdrantClient(url=q_url, timeout=2.0)
            client.get_collections()
            return client
        except Exception:
            return QdrantClient(path="./qdrant_db")
    elif q_url.startswith("/") or q_url.startswith("./") or q_url == ":memory:":
        return QdrantClient(path=q_url) if q_url != ":memory:" else QdrantClient(location=":memory:")
    return QdrantClient(url=q_url)


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
