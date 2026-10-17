"""Where an obligation came from: circular, section, clause number, page and text."""
from sqlalchemy.orm import Session

from app.db.models import Clause, Obligation


def obligation_source(db: Session, obligation: Obligation, vector_payload: dict | None = None) -> dict:
    """Resolve an obligation's source from Postgres (the system of record).

    Falls back to the Qdrant payload for the text/circular only when the Postgres lineage
    is missing (e.g. obligations created before lineage tracking existed).
    """
    clause = db.get(Clause, obligation.clause_uuid) if obligation.clause_uuid else None
    vector_payload = vector_payload or {}
    return {
        "circular_id": obligation.origin_circular_id or vector_payload.get("circular_id"),
        "section": clause.section.title if clause and clause.section else None,
        "clause_number": clause.clause_number if clause else None,
        "page": clause.page if clause else None,
        "text": (clause.text if clause else None) or vector_payload.get("text"),
    }
