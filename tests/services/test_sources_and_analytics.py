from types import SimpleNamespace as NS

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Circular, Clause, Obligation, Section
from app.services.review_analytics import summarize_reviews
from app.services.sources import obligation_source


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Circular(id="circ"))
    db.add(Section(id="s1", title="Risk Management", circular_id="circ"))
    db.add(Clause(id="cl1", clause_number="4.2", text="Brokers shall X.", page=7, section_id="s1"))
    db.commit()
    return db


def test_source_comes_from_postgres_lineage():
    db = _db()
    ob = Obligation(id="o1", clause_uuid="cl1", origin_circular_id="circ")
    assert obligation_source(db, ob) == {
        "circular_id": "circ", "section": "Risk Management", "clause_number": "4.2",
        "page": 7, "text": "Brokers shall X.",
    }


def test_source_falls_back_to_the_vector_payload_without_lineage():
    db = _db()
    ob = Obligation(id="o2")
    src = obligation_source(db, ob, {"text": "from qdrant", "circular_id": "old-circ"})
    assert src["text"] == "from qdrant" and src["circular_id"] == "old-circ"
    assert src["page"] is None and src["clause_number"] is None


def test_source_with_nothing_known_is_all_none():
    assert obligation_source(_db(), Obligation(id="o3")) == {
        "circular_id": None, "section": None, "clause_number": None, "page": None, "text": None}


def _r(status, conf):
    return NS(status=status, confidence=conf)


def test_review_analytics_override_rate_by_band():
    items = [
        _r("approved", 0.9), _r("approved", 0.95), _r("rejected", 0.85),   # high: 1/3 overridden
        _r("edited", 0.6), _r("approved", 0.7),                             # medium: 1/2
        _r("rejected", 0.2),                                                # low: 1/1
        _r("approved", None),                                               # unscored
        _r("pending", 0.4),
    ]
    out = summarize_reviews(items)
    bands = {b["band"]: b for b in out["by_confidence_band"]}
    assert out["pending"] == 1
    assert bands["high (>=0.80)"]["reviewed"] == 3
    assert abs(bands["high (>=0.80)"]["override_rate"] - 1 / 3) < 1e-9
    assert bands["medium (0.50-0.80)"]["override_rate"] == 0.5
    assert bands["low (<0.50)"]["override_rate"] == 1.0
    assert out["overall"]["reviewed"] == 7
    assert out["unscored"]["approved"] == 1


def test_review_analytics_with_no_data():
    out = summarize_reviews([])
    assert out["overall"]["override_rate"] is None
    assert out["unscored"] is None
    assert all(b["override_rate"] is None for b in out["by_confidence_band"])
