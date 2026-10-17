# Migration Notes — RegOps AI Version 2 Schema Upgrades

This document outlines the database schema alterations, migration execution paths, and lineage traversal details introduced in Version 2.

---

## 1. Schema Alterations

The database schema has been expanded to support detailed regulatory lineage traversal, version tracking, and structured parent-child dependencies.

### Modified Tables
- **`obligations`**:
  - `previous_obligation_id` (`String`, `ForeignKey("obligations.id")`): Tracks the historical version of an obligation.
  - `amended_obligation_id` (`String`, `ForeignKey("obligations.id")`): Points to the obligation version that amended this rule.
  - `superseded_obligation_id` (`String`, `ForeignKey("obligations.id")`): Points to the obligation version that superseded this rule.
  - `origin_circular_id` (`String`, `ForeignKey("circulars.id")`): Links the obligation back to its source circular.
  - `clause_uuid` (`String`, `ForeignKey("clauses.id")`): Links the obligation back to its parent clause node in the layout tree.

### New Relational Tables
- **`circulars`**:
  - Columns: `id` (PK), `title`, `issue_date`
- **`sections`**:
  - Columns: `id` (PK), `title`, `circular_id` (FK to `circulars.id`)
- **`clauses`**:
  - Columns: `id` (PK), `clause_number`, `text`, `section_id` (FK to `sections.id`)
- **`deadlines`**:
  - Columns: `id` (PK), `due_date`, `status` (open/met), `obligation_id` (FK to `obligations.id`)
- **`applicable_entities`**:
  - Columns: `id` (PK), `entity_name`, `obligation_id` (FK to `obligations.id`)
- **`evidence`**:
  - Columns: `id` (PK), `file_ref`, `submitted_at`, `obligation_id` (FK to `obligations.id`)
- **`review_queue`**:
  - Columns: `id` (PK, matches thread ID), `circular_id`, `clause_id`, `previous_clause`, `new_clause`, `highlighted_diff`, `llm_explanation`, `confidence`, `extracted_obligation` (JSON), `status` (pending/approved/rejected/edited)

---

## 2. Dynamic Auto-Migration Utility

To ensure backward compatibility and prevent manual DB overhead, schema migration is driven automatically at app initialization.

- **Migration Script**: superseded by Alembic (`migrations/`, run via `app.db.migrate.run_migrations`).
- **Execution Hook**: Configured inside the FastAPI startup Lifespan handler in [main.py](file:///home/krisharish/Documents/complyguard-sebi-gff-hackathon-2026/app/api/main.py).
- **Behavior**:
  1. Inspects the database tables. If the `obligations` table exists but lacks V2 columns, it runs SQL `ALTER TABLE` commands to inject `previous_obligation_id`, `amended_obligation_id`, `superseded_obligation_id`, `origin_circular_id`, and `clause_uuid`.
  2. Resolves SQLite constraints dynamically.
  3. Pre-populates default schemas safely.

---

## 3. How to Run Migrations Manually

While migrations execute automatically at startup, you can trigger a manual migration by executing:

```bash
alembic upgrade head
```
