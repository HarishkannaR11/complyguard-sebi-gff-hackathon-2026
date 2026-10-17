import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Circular, Clause, Obligation, Section
from app.embeddings.qdrant_client import ensure_collection, find_by_obligation_id, upsert_chunks
from app.services.reconcile import reconcile_vectors


def fake_embed(texts):
    return [[float(len(t)), 1.0, 0.0, 0.5] for t in texts]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Circular(id="circ"))
    session.add(Section(id="sec", title="General", circular_id="circ"))
    session.add(Clause(id="cl-1", clause_number="1", text="Maintain records for five years.", section_id="sec"))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def qdrant():
    client = QdrantClient(location=":memory:")
    ensure_collection(client, vector_size=4)
    return client


def _obligation(db, oid, **kw):
    db.add(Obligation(id=oid, clause_id="clause-0", requirement="r", origin_circular_id="circ",
                      status=kw.pop("status", "active"), source_type=kw.pop("source_type", "regulatory"), **kw))
    db.commit()


def test_in_sync_store_reports_nothing(db, qdrant):
    _obligation(db, "o1", clause_uuid="cl-1")
    upsert_chunks(qdrant, ["t"], [[1.0, 0.0, 0.0, 0.0]], [{"obligation_id": "o1"}])
    result = reconcile_vectors(db, qdrant, fake_embed)
    assert result["missing_vectors"] == [] and result["orphaned_vectors"] == []


def test_missing_vector_is_detected_and_repaired_from_clause_text(db, qdrant):
    _obligation(db, "o1", clause_uuid="cl-1")
    result = reconcile_vectors(db, qdrant, fake_embed)
    assert result["missing_vectors"] == ["o1"]
    assert result["repaired"] == ["o1"]
    payload = find_by_obligation_id(qdrant, "o1")
    assert payload["text"] == "Maintain records for five years."
    assert payload["circular_id"] == "circ"
    # second run is clean
    assert reconcile_vectors(db, qdrant, fake_embed)["missing_vectors"] == []


def test_dry_run_changes_nothing(db, qdrant):
    _obligation(db, "o1", clause_uuid="cl-1")
    result = reconcile_vectors(db, qdrant, fake_embed, fix=False)
    assert result["missing_vectors"] == ["o1"] and result["repaired"] == []
    assert find_by_obligation_id(qdrant, "o1") is None


def test_obligation_without_clause_text_is_reported_unrecoverable(db, qdrant):
    _obligation(db, "o2")  # no clause_uuid
    result = reconcile_vectors(db, qdrant, fake_embed)
    assert result["unrecoverable"] == ["o2"] and result["repaired"] == []


def test_orphan_vector_is_deleted_but_company_and_superseded_rows_are_not_orphans(db, qdrant):
    _obligation(db, "old", clause_uuid="cl-1", status="superseded")
    upsert_chunks(qdrant, ["a", "b"], [[1.0, 0, 0, 0], [0, 1.0, 0, 0]],
                  [{"obligation_id": "old"}, {"obligation_id": "ghost"}])
    result = reconcile_vectors(db, qdrant, fake_embed)
    assert result["orphaned_vectors"] == ["ghost"]
    assert result["orphans_deleted"] == ["ghost"]
    assert find_by_obligation_id(qdrant, "ghost") is None
    assert find_by_obligation_id(qdrant, "old") is not None
    assert "old" not in result["missing_vectors"]  # superseded rows aren't expected in Qdrant


def test_company_obligations_are_ignored(db, qdrant):
    _obligation(db, "c1", source_type="company")
    assert reconcile_vectors(db, qdrant, fake_embed)["obligations_checked"] == 0


def test_missing_collection_is_handled(db):
    client = QdrantClient(location=":memory:")  # no collection yet
    _obligation(db, "o1", clause_uuid="cl-1")
    result = reconcile_vectors(db, client, fake_embed)
    assert result["repaired"] == ["o1"]
