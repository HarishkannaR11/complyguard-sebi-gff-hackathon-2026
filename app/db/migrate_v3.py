"""
migrate_v3.py

Database migration for workflow separation:
- Adds `source_type` column to obligations (values: 'regulatory' | 'company')
- Creates company_obligations table
- Creates gap_results table
Runs automatically during application startup.
"""

import os
from sqlalchemy import create_engine, text


def run_migrations():
    conn_string = os.environ.get(
        "DATABASE_URL", "postgresql://regops:regops@localhost:5433/regops"
    )
    is_sqlite = conn_string.startswith("sqlite")

    engine = create_engine(conn_string)

    print("[MIGRATION v3] Running workflow separation migrations...")

    with engine.begin() as conn:
        # ── 1. Add source_type to obligations ──────────────────────────────
        if is_sqlite:
            try:
                res = conn.execute(text("PRAGMA table_info(obligations)"))
                existing_cols = [row[1] for row in res.fetchall()]
            except Exception:
                existing_cols = []
        else:
            try:
                res = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='obligations'"
                ))
                existing_cols = [row[0] for row in res.fetchall()]
            except Exception:
                existing_cols = []

        if existing_cols and "source_type" not in existing_cols:
            print("[MIGRATION v3] Adding source_type column to obligations table.")
            try:
                conn.execute(text(
                    "ALTER TABLE obligations ADD COLUMN source_type VARCHAR DEFAULT 'regulatory'"
                ))
            except Exception as e:
                print(f"[MIGRATION v3 WARNING] Could not add source_type: {e}")

        # ── 2. Create company_obligations table ────────────────────────────
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS company_obligations (
                    id VARCHAR PRIMARY KEY,
                    requirement TEXT,
                    frequency VARCHAR,
                    evidence_type VARCHAR,
                    deadline_rule VARCHAR,
                    intermediary VARCHAR DEFAULT 'stockbroker',
                    owner VARCHAR DEFAULT 'compliance',
                    due_date DATETIME,
                    status VARCHAR DEFAULT 'open',
                    imported_at DATETIME,
                    source_file VARCHAR
                )
            """))
            print("[MIGRATION v3] company_obligations table ready.")
        except Exception as e:
            print(f"[MIGRATION v3 WARNING] company_obligations table: {e}")

        # ── 3. Create gap_results table ────────────────────────────────────
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS gap_results (
                    id VARCHAR PRIMARY KEY,
                    regulatory_obligation_id VARCHAR,
                    company_obligation_id VARCHAR,
                    gap_type VARCHAR,
                    detail TEXT,
                    computed_at DATETIME
                )
            """))
            print("[MIGRATION v3] gap_results table ready.")
        except Exception as e:
            print(f"[MIGRATION v3 WARNING] gap_results table: {e}")

    print("[MIGRATION v3] Done.")
