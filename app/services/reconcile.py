"""Detect and repair drift between Postgres obligations and their Qdrant vectors.

``mapper`` commits the Obligation row and then upserts its vector; the two stores
cannot share a transaction, so a crash or Qdrant outage in between leaves an
obligation without a vector (invisible to ``differ`` and to source tracing). The
reverse -- a vector whose obligation was deleted -- is also possible.
"""
import logging
from typing import Callable

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy.orm import Session

from app.db.models import SOURCE_REGULATORY, Clause, Obligation
from app.embeddings.qdrant_client import DEFAULT_COLLECTION, ensure_collection, upsert_chunks

logger = logging.getLogger(__name__)


def _all_vector_obligation_ids(client, collection_name: str) -> set[str]:
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name, limit=256, offset=offset,
            with_payload=["obligation_id"], with_vectors=False,
        )
        for point in points:
            oid = (point.payload or {}).get("obligation_id")
            if oid:
                ids.add(oid)
        if offset is None:
            return ids


def reconcile_vectors(
    db: Session,
    client,
    embed: Callable[[list[str]], list[list[float]]],
    *,
    fix: bool = True,
    collection_name: str = DEFAULT_COLLECTION,
) -> dict:
    """Compare active regulatory obligations with Qdrant. With ``fix`` re-embed the
    missing ones from their stored clause text and delete orphaned vectors."""
    obligations = (
        db.query(Obligation)
        .filter(Obligation.status == "active", Obligation.source_type == SOURCE_REGULATORY)
        .all()
    )
    known_ids = {oid for (oid,) in db.query(Obligation.id).all()}

    existing = client.get_collections().collections
    collection_exists = any(c.name == collection_name for c in existing)
    vector_ids = _all_vector_obligation_ids(client, collection_name) if collection_exists else set()

    missing = [o for o in obligations if o.id not in vector_ids]
    orphans = sorted(vector_ids - known_ids)

    repaired, unrecoverable = [], []
    for obligation in missing:
        clause = db.get(Clause, obligation.clause_uuid) if obligation.clause_uuid else None
        if clause is None or not (clause.text or "").strip():
            unrecoverable.append(obligation.id)
            continue
        if not fix:
            continue
        vector = embed([clause.text])[0]
        ensure_collection(client, collection_name, vector_size=len(vector))
        upsert_chunks(
            client, [clause.text], [vector],
            [{
                "circular_id": obligation.origin_circular_id,
                "clause_id": obligation.clause_id,
                "obligation_id": obligation.id,
            }],
            collection_name=collection_name,
        )
        repaired.append(obligation.id)

    deleted_orphans: list[str] = []
    if fix:
        for orphan_id in orphans:
            client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=Filter(must=[
                    FieldCondition(key="obligation_id", match=MatchValue(value=orphan_id))
                ])),
            )
            deleted_orphans.append(orphan_id)

    logger.info(
        "vector reconcile: %d missing (%d repaired, %d unrecoverable), %d orphaned (%d deleted)",
        len(missing), len(repaired), len(unrecoverable), len(orphans), len(deleted_orphans),
    )
    return {
        "fix": fix,
        "obligations_checked": len(obligations),
        "missing_vectors": [o.id for o in missing],
        "repaired": repaired,
        "unrecoverable": unrecoverable,
        "orphaned_vectors": orphans,
        "orphans_deleted": deleted_orphans,
    }
