"""Import-safety checks for modules still awaiting user-provided implementation,
plus a sanity check that the now-real graph/model/route/ingestion modules import
cleanly."""
import pytest

from app.api.routes_review import router
from app.db.models import AuditTrail, EvidenceLog, Obligation, Task
from app.db.seed_synthetic import seed
from app.graph.build_graph import build_graph
from app.graph.state import ComplianceState
from app.ingestion.pdf_cleaner import extract_and_clean
from scripts.generate_synthetic_data import generate


def test_remaining_stub_functions_raise_not_implemented_when_called():
    # seed() is now implemented and should not raise NotImplementedError
    seed()
    with pytest.raises(NotImplementedError):
        generate()


def test_real_graph_db_route_and_ingestion_modules_import_cleanly():
    assert callable(build_graph)
    assert callable(extract_and_clean)
    assert {"circular_id", "clause_id", "raw_clause", "diff_status"} <= set(
        ComplianceState.__annotations__
    )
    assert Obligation.__tablename__ == "obligations"
    assert Task.__tablename__ == "tasks"
    assert EvidenceLog.__tablename__ == "evidence_log"
    assert AuditTrail.__tablename__ == "audit_trail"
    assert router is not None
