"""
migrate_v2.py

Automated database migration helper to add lineage columns to the existing obligations table.
Runs dynamically during application startup.
"""

import os
from sqlalchemy import create_engine, text


def run_migrations():
    conn_string = os.environ.get(
        "DATABASE_URL", "postgresql://regops:regops@localhost:5433/regops"
    )
    is_sqlite = conn_string.startswith("sqlite")

    engine = create_engine(conn_string)

    # Columns to add to the existing obligations table
    cols_to_add = [
        ("previous_obligation_id", "VARCHAR"),
        ("amended_obligation_id", "VARCHAR"),
        ("superseded_obligation_id", "VARCHAR"),
        ("origin_circular_id", "VARCHAR"),
        ("clause_uuid", "VARCHAR"),
    ]

    print("[MIGRATION] Checking for obligations table lineage columns...")
    with engine.begin() as conn:
        if is_sqlite:
            # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
            try:
                res = conn.execute(text("PRAGMA table_info(obligations)"))
                existing_cols = [row[1] for row in res.fetchall()]
            except Exception as e:
                print(f"[MIGRATION WARNING] Table info read failed: {e}. obligations table may not exist yet.")
                existing_cols = []
        else:
            try:
                res = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='obligations'"
                ))
                existing_cols = [row[0] for row in res.fetchall()]
            except Exception as e:
                print(f"[MIGRATION WARNING] Table column query failed: {e}.")
                existing_cols = []

        if existing_cols:
            for col_name, col_type in cols_to_add:
                if col_name not in existing_cols:
                    print(f"[MIGRATION] Adding column {col_name} to obligations table.")
                    try:
                        conn.execute(text(f"ALTER TABLE obligations ADD COLUMN {col_name} {col_type}"))
                    except Exception as e:
                        print(f"[MIGRATION WARNING] Failed to add column {col_name}: {e}")
        else:
            print("[MIGRATION] obligations table does not exist or has not been created yet. Schema generation will handle this.")
