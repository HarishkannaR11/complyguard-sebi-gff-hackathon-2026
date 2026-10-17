from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

import app.db.models  # noqa: F401
from app.db.database import Base
from app.db.migrate import run_migrations


def _url(tmp_path):
    return f"sqlite:///{tmp_path / 'm.db'}"


def test_fresh_database_gets_every_table(tmp_path):
    url = _url(tmp_path)
    run_migrations(url)
    inspector = inspect(create_engine(url))
    assert set(Base.metadata.tables) <= set(inspector.get_table_names())
    assert "alembic_version" in inspector.get_table_names()


def test_migrations_are_idempotent(tmp_path):
    url = _url(tmp_path)
    run_migrations(url)
    run_migrations(url)


def test_models_and_migrations_have_not_drifted(tmp_path):
    """Fails when someone changes models.py without adding a migration."""
    url = _url(tmp_path)
    run_migrations(url)
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_legacy_database_is_upgraded_in_place_without_losing_data(tmp_path):
    """A DB from before the lineage / source_type columns existed."""
    url = _url(tmp_path)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE obligations (id VARCHAR PRIMARY KEY, clause_id VARCHAR, requirement TEXT,"
            " frequency VARCHAR, evidence_type VARCHAR, deadline_rule VARCHAR,"
            " intermediary VARCHAR, status VARCHAR)"
        ))
        conn.execute(text("INSERT INTO obligations (id, requirement) VALUES ('o1', 'keep me')"))

    run_migrations(url)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("obligations")}
    assert {"previous_obligation_id", "amended_obligation_id", "superseded_obligation_id",
            "origin_circular_id", "clause_uuid", "source_type"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT requirement FROM obligations WHERE id='o1'")).scalar() == "keep me"
    assert "upload_jobs" in inspector.get_table_names()
