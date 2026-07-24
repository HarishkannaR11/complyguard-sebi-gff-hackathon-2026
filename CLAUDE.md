# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RegOps AI — an agentic compliance copilot for SEBI-regulated intermediaries. A user uploads a SEBI
circular PDF; the system cleans and clause-splits it, embeds and diffs each clause against previously
seen clauses, extracts structured obligations via an LLM, routes uncertain diffs to a human reviewer,
and tracks each obligation as a `Task` with a due date, evidence, and status (pending/met/overdue) in
Postgres. Every pipeline run appends a hash-chained `AuditTrail` row for tamper-evident traceability.

This is a hackathon prototype under active restructuring (see `docs/superpowers/specs/` and
`docs/superpowers/plans/` for the design docs and implementation plans that produced the current
codebase — read those before making structural changes, they contain the reasoning for non-obvious
decisions referenced below).

## Commands

### Backend

```bash
# infra (Postgres on host port 5433, Qdrant on 6333/6334)
docker compose up -d

# python env
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY

# run all tests
python -m pytest

# run one test file / one test
python -m pytest tests/graph/test_nodes.py
python -m pytest tests/graph/test_nodes.py::test_chunker_node_strips_and_derives_heading -v

# run the API
uvicorn app.api.main:app --reload --port 8000

# ingest a circular into Qdrant only (no DB writes, no LLM)
python -m app.ingestion.pdf_cleaner data/raw_pdfs/<circular>.pdf
python -m scripts.run_ingest data/raw_pdfs/<circular>.pdf

# run the full extraction/diff graph over one clause
python -m scripts.run_diff <circular_id> <clause_id> '<raw clause text>'
```

`pytest.ini` sets `pythonpath = .` — tests import `app.*` as installed-package-style absolute imports,
not relative; run pytest from the repo root.

### Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, talks to API at http://localhost:8000
npm run build
npm run lint       # oxlint
```

## Architecture

### Pipeline shape

```
PDF → pdf_cleaner → clause_splitter → [per clause, through a LangGraph state machine] → Postgres + Qdrant
```

The per-clause graph (`app/graph/build_graph.py`, nodes in `app/graph/nodes.py`) is the core of the
system. Each clause of an uploaded circular is run through it independently, keyed by
`thread_id = f"{circular_id}:{clause_id}"` in a Postgres-backed LangGraph checkpointer — this is what
lets a paused (human-review) run be resumed later by that same thread_id.

Node sequence and routing (`ComplianceState` in `app/graph/state.py`):

```
chunker → embedder → extractor → differ ─┬─ (new)              → mapper → evidence_check ─┬─ (present) → finalize
                                          ├─ (amended/superseded)→ human_review → mapper       ├─ (missing) → gap_engine → finalize
                                          └─ (unchanged)         → finalize                    └─ (invalid) → human_review
```

- **differ** does a Qdrant similarity search (`SIMILARITY_THRESHOLD = 0.85`) against previously
  ingested clauses to classify the clause as `new` / `unchanged` / `amended`. It never writes to
  Qdrant — that's `mapper`'s job, once a real `obligation_id` exists to attach to the payload.
- **human_review** is the only node that calls `langgraph.types.interrupt(...)`, pausing the graph.
  `app/api/routes_review.py`'s `POST /review/{thread_id}/decision` resumes it via
  `Command(resume={"decision": ..., "actor": ...})`. Decisions: `"approve"`, `"reject"`, or
  `"amend:<json>"` (merges the JSON suffix into `extracted_obligation`).
- **mapper** is a no-op when `human_decision == "reject"` or `diff_status == "unchanged"` — nothing to
  persist. Otherwise it inserts (new) or updates (amended, matched via
  `similarity_match["payload"]["obligation_id"]`) an `Obligation` row, creates a `Task` row with a
  due date resolved from `deadline_rule` (ISO date, a frequency keyword in `FREQUENCY_DAYS`, or open-
  ended → `None`), and upserts the clause's embedding into Qdrant with `obligation_id` in the payload
  so future `differ` runs can resolve back to this row.
- **finalize** always writes exactly one hash-chained `AuditTrail` row per run
  (`hash = sha256(prev_hash + json(action) + timestamp)`), reading the previous row's `hash` as
  `prev_hash`. This chain is what makes the audit log tamper-evident. Known limitation, documented
  in `_write_audit_entry`'s comment: the read-latest-then-commit sequence is not concurrency-safe
  under simultaneous writers — acceptable for this app's single-request-at-a-time usage, not fixed.

Supersession (an obligation whose clause disappeared entirely from a newer circular version) is
**not** a graph node — `app/services/supersession.py`'s `mark_superseded_obligations()` is a
batch-level function `app/api/main.py`'s `POST /upload` calls once after every clause in the upload
has been run through the graph, and only if none of them errored (a partial run must not be trusted
to say "this obligation is gone").

### Data model (`app/db/models.py`, Postgres via SQLAlchemy)

`Obligation` (status: active/superseded) 1—N `Task` (status: pending/met/overdue, computed by
`app/services/gap_engine.py::compute_status`, never stored as a raw boolean) 1—N `EvidenceLog`.
`AuditTrail` is independent, keyed by `thread_id`/`node_name`, and is the hash chain described above.
`models.py` imports `Base` from `app.db.database` (not its own `declarative_base()`) — this is load-
bearing: `Base.metadata.create_all()` in `app/api/main.py`'s lifespan hook only sees tables registered
against the one shared `Base`.

### Vector store (Qdrant, `app/embeddings/qdrant_client.py`)

Single collection `circular_clauses`, 768-dim (`BAAI/bge-base-en-v1.5`), cosine distance. Payload per
point: `text`, `circular_id`, `clause_id`, `obligation_id`. `search()` returns `text`/`score`/`payload`
per hit; `find_by_obligation_id()` does a payload-filtered scroll and is how `GET /obligations` recovers
the traceable `source_chunk` for a given obligation.

### API (`app/api/main.py`, `app/api/routes_review.py`)

`POST /upload` runs the whole per-clause pipeline synchronously in the request and returns per-clause
results plus any newly superseded obligation ids. `GET /obligations`, `GET /gaps`, `GET /evidence`,
`POST /evidence`, `GET /audit_log`, `POST /review/{thread_id}/decision`. `GET /gaps` and
`GET /obligations` both call `update_all_task_statuses()` first so status is always recomputed against
today's date rather than trusting a stale stored value.

### Frontend (`frontend/src`)

Plain React 19 + Vite + Tailwind 4, no router — `App.jsx` switches between views
(`components/views/{Landing,Hero,UploadCircular,ObligationList,GapDashboard,AuditTrail}.jsx`) via local
state. `api.js` is a thin fetch wrapper hardcoded to `http://localhost:8000`. `data/mockData.js` exists
for UI development without a live backend.

## Known incomplete pieces

`app/db/seed_synthetic.py` and `scripts/generate_synthetic_data.py` are placeholder stubs
(`raise NotImplementedError`) — the README describes what they're meant to produce (6 obligations, 143
tasks, 129 evidence rows, 25 grievances, org roles) but the real implementations haven't been pasted in
yet. Don't assume `python -m app.db.seed_synthetic` works.

## Conventions specific to this codebase

- Graph nodes are plain functions `(state: ComplianceState) -> dict` returning only the keys they
  change — LangGraph merges partial updates. Never mutate `state` in place.
- `DATABASE_URL` / `QDRANT_URL` / `GROQ_API_KEY` / `GROQ_MODEL` are read from the environment at the
  point of use (`os.environ.get(...)` with a hardcoded fallback matching `docker-compose.yml`), not
  imported as constants — this is why `.env` must be loaded (`load_dotenv()` in `app/api/main.py`)
  *before* `app.db.database` is imported anywhere.
- Pure business logic (`compute_status`, `resolve_due_date`, `compute_audit_hash`,
  `split_into_clauses`) is kept dependency-free and unit-tested directly, with no mocking. Anything
  touching Groq/Qdrant/Postgres is tested via mocks (see `tests/embeddings/test_qdrant_client.py`,
  `tests/graph/test_nodes.py` for the established pattern) rather than requiring live services in CI.
- Postgres host port is `5433`, not the default `5432` — this machine has an unrelated project's
  Postgres already bound to `5432` (see the comment in `docker-compose.yml`). Don't "fix" this back to
  5432.
