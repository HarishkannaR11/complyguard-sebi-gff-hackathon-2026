# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RegOps AI — an agentic compliance copilot for SEBI-regulated intermediaries. A user uploads a SEBI
circular PDF; the system parses it into structured clauses, embeds and diffs each clause against
previously seen clauses, extracts structured obligations via an LLM, validates them, routes uncertain
results to a human reviewer, and tracks each obligation as a `Task` with a due date, evidence, and
status (pending/met/overdue) in Postgres. A second workflow imports the company's own obligations (CSV)
and runs a gap analysis against the regulatory ones. Every pipeline run appends hash-chained
`AuditTrail` rows for tamper-evident traceability.

Design history lives in `docs/superpowers/` (specs and plans) and `docs/history/` (V2 changelog, bug
record, old migration notes). `PIPELINE.md` is the long-form pipeline write-up. Read the specs before
making structural changes — they contain the reasoning for non-obvious decisions.

## Commands

### Backend

```bash
# infra (Postgres on host port 5433, Qdrant on 6333/6334)
docker compose up -d

# python env
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY

# run all tests (needs Postgres on :5433 for tests/test_stubs.py's seed() -- CI provides one)
python -m pytest
python -m pytest tests/graph/test_nodes.py::test_chunker_node_strips_and_derives_heading -v

# run the API (applies Alembic migrations and sets up the LangGraph checkpointer at startup)
uvicorn app.api.main:app --reload --port 8000

# database migrations (Alembic; URL comes from DATABASE_URL)
alembic upgrade head
alembic revision --autogenerate -m "what changed"   # after editing app/db/models.py
alembic check                                        # fails if models and migrations disagree

# evaluation harness (live Groq calls; see evals/README.md)
python -m evals.run_eval

# ingest a circular into Qdrant only (no DB writes, no LLM)
python -m scripts.run_ingest data/raw_pdfs/<circular>.pdf

# run the full extraction/diff graph over one clause
python -m scripts.run_diff <circular_id> <clause_id> '<raw clause text>'
```

`pytest.ini` sets `pythonpath = .` — tests import `app.*` as absolute imports; run pytest from the repo
root. `tests/conftest.py` sets `ALLOW_MEMORY_CHECKPOINTER=1` and a dummy `GROQ_API_KEY` so unit tests
need neither Postgres checkpointing nor a real key.

### Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint      # oxlint
```

Config: `VITE_API_URL` (default `http://localhost:8000`) and `VITE_API_KEY` (sent as `X-API-Key`); see
`frontend/.env.example`.

### CI

`.github/workflows/ci.yml`: backend job (Postgres 16 service on 5433, `alembic upgrade head`,
`alembic check`, `pytest`) and frontend job (`npm ci`, lint, build).

## Architecture

### Pipeline shape

```
PDF → hybrid_parser (page/section/clause/confidence per chunk) → [per clause, through a LangGraph state machine] → Postgres + Qdrant
```

`POST /upload` validates and parses the PDF synchronously (a bad PDF is still a 422), then runs the
per-clause pipeline as a **background job** (see "Upload jobs"). The pipeline itself lives in
`app/services/upload_pipeline.py` (`parse_circular`, `process_chunks`); the HTTP layer only wires it up.

The per-clause graph (`app/graph/build_graph.py`, nodes in `app/graph/nodes.py`) is the core. Each clause
runs independently, keyed by `thread_id = f"{circular_id}:{clause_id}"` in a Postgres-backed LangGraph
checkpointer — this is what lets a paused (human-review) run be resumed later by that same thread_id.

```
chunker → embedder → extractor → validation ─┬─ (failed, retries left) → extractor
                                             └─ differ ─┬─ (new, confident)        → mapper → evidence_check ─┬─ (present) → finalize
                                                        ├─ (amended/superseded,     → human_review → mapper    ├─ (missing) → gap_engine → finalize
                                                        │   low confidence, or                                 └─ (invalid) → human_review
                                                        │   validation failed)
                                                        └─ (unchanged)             → finalize
```

- **validation** checks the extractor output with the `ExtractedObligation` pydantic model and loops back
  to `extractor` (bounded by `extraction_retries`).
- **differ** does a Qdrant top-3 search, then asks the LLM to classify the clause as
  `new`/`unchanged`/`amended`/`superseded` against the candidates. It never writes to Qdrant.
- **route_after_diff** sends a clause to `human_review` when validation failed, when
  `overall_confidence < EXTRACTION_CONFIDENCE_MIN` (0.8), when the parser's `confidence <
  PARSE_CONFIDENCE_MIN` (0.7), or when the diff is amended/superseded. The constants are in
  `build_graph.py`; use `evals/` (confidence-threshold sweep) and `GET /review/analytics` (override rate per
  confidence band) to tune them.
- **human_review** is the only node that calls `interrupt(...)`. It writes a `ReviewQueue` row (with the
  clause's section/number/page and an HTML-escaped word diff) and resumes via
  `Command(resume={"decision": ..., "actor": ...})`. Decisions: `approve`, `reject`, `amend:<json>`.
- **mapper** is a no-op on `reject`/`unchanged`. Otherwise it inserts/updates an `Obligation`, creates a
  `Task` (due date from `deadline_rule`: ISO date, a `FREQUENCY_DAYS` keyword, or none), and upserts the
  clause vector into Qdrant with `obligation_id`. Postgres and Qdrant cannot share a transaction; if the
  vector write fails it logs a repair hint and re-raises, and `POST /admin/reconcile-vectors` repairs it.
- **finalize** writes a hash-chained `AuditTrail` row per run.

Supersession (an obligation whose clause vanished from a newer circular) is **not** a graph node —
`app/services/supersession.py` runs once after all clauses of an upload, and only if none errored.

### Upload jobs

`POST /upload` returns **202** + `job_id`; poll `GET /jobs/{id}` (`status` queued/running/completed/failed,
`clauses_done/total`, `result`). `?wait=true` runs inline and returns the full result (scripts, tests).
Jobs are rows in `upload_jobs`; any left queued/running by a restart are marked failed at startup. The
frontend's `uploadCircular()` polls and resolves with the old result shape.

Gotcha (found against real Postgres): never leave a request-scoped DB session holding a transaction while
the background job runs, and set up the checkpointer at startup (`init_checkpointer()` in the lifespan hook)
— `PostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which waits for every open transaction.

### Workflow state

`app/services/workflow_state.py` + `app/api/routes_workflow.py` hold a single-row state machine
(IDLE → … → REVIEW_APPROVED → REGULATORY_COMPLETE → COMPANY_DATA_IMPORTED → GAP_ANALYSIS_COMPLETE →
DASHBOARD_READY) that gates the UI. `advance()` only moves forward.

### Data model (`app/db/models.py`, Postgres via SQLAlchemy)

- Lineage: `Circular` 1—N `Section` 1—N `Clause` (stores text and PDF `page`).
- `Obligation` (status active/superseded; `source_type` regulatory/company; lineage FKs to previous /
  amended / superseded obligations, `origin_circular_id`, `clause_uuid`) 1—N `Task`
  (pending/met/overdue, computed by `app/services/gap_engine.py::compute_status`) 1—N `EvidenceLog`.
- `ReviewQueue`, `CompanyObligation`, `GapResult`, `WorkflowStateRecord`, `UploadJob`.
- `AuditTrail` is independent, keyed by `thread_id`/`node_name`, and is the hash chain.

`models.py` imports `Base` from `app.db.database` (load-bearing: one shared `Base`). **Schema changes go
through Alembic** (`migrations/`); the baseline is idempotent so it also upgrades databases created by the
old `create_all` + `migrate_v2/v3` scripts. `tests/db/test_migrate.py` fails if models and migrations drift.

### Audit trail

`hash = sha256(prev_hash + json(action, sort_keys) + timestamp)` (`app/services/audit.py`). **Write rows only
through `nodes._write_audit_entry`** (process lock + `SELECT … FOR UPDATE`); a raw `AuditTrail(...)` insert
without hashes forks the chain. `GET /audit_log/verify` re-walks the chain through `prev_hash` links and
reports the first tampered, missing or forked entry.

### Vector store (Qdrant, `app/embeddings/qdrant_client.py`)

Single collection `circular_clauses`, 768-dim (`BAAI/bge-base-en-v1.5`), cosine. Payload: `text`,
`circular_id`, `clause_id`, `obligation_id`. `get_client()` returns one cached client per URL. If a *local*
server is unreachable it falls back to an embedded `./qdrant_db` store — with an error log, re-probing
every 30 s, and `/health` reporting `degraded`. `QDRANT_URL=":memory:"` gives an in-memory store. A remote server gets `QDRANT_API_KEY` if set (Qdrant Cloud).
`app/services/sources.py` resolves an obligation's source (circular, section, clause no., page, text) from
Postgres first; Qdrant is only a fallback.

### LLM access

All Groq calls go through `app/llm/groq_client.py::chat_completion` — one cached client, JSON-mode
responses, exponential backoff with jitter on connection errors / timeouts / 429 / 5xx (honours
`Retry-After`). Don't construct `Groq(...)` in nodes. `GROQ_API_KEY` and `GROQ_MODEL` are read at call time.

### API

`app/api/main.py`: `/livez` (public, shallow — use for load-balancer/container health) and `/health` (public, deep:
Postgres + Qdrant, 503 if down), `/readiness`, `POST /upload`, `GET /jobs/{id}`,
`POST /import/obligations` (company CSV), `/gaps`, `/gaps/legacy`, `/obligations`, `/company-obligations`,
`/evidence`, `/audit_log`, `/audit_log/verify`, `POST /admin/reconcile-vectors?fix=true|false`, `/metrics`.
`routes_review.py`: `/review/queue`, `/review/analytics`, `POST /review/{thread_id}/submit|decision`.
`routes_workflow.py`: workflow-state endpoints. `/gaps` and `/obligations` recompute task statuses first.

### Security

- **Auth:** `API_KEYS="key:user,key2:user2"` enables `X-API-Key` auth on every route except `/health` and the
  docs (`app/api/security.py`). Unset = open (local dev). With auth on, the key's user is the audit `actor`
  for review decisions; a client-supplied `actor` is ignored.
- **CORS:** only `CORS_ORIGINS` (default the Vite dev origins); no wildcard, no credentials.
- **Uploads:** `.pdf` + `%PDF-` magic + `MAX_UPLOAD_MB` (default 25) + sanitised filename (no path
  traversal); CSV import has the same size/extension checks.
- **HTML:** `generate_text_diff` HTML-escapes every word because the review UI renders it with
  `dangerouslySetInnerHTML`. Keep it that way.

### Evaluation (`evals/`)

Labelled extraction (24) and diff (16) cases plus a runner that reports per-field accuracy, diff
precision/recall, and a confidence-threshold sweep. Cases are synthetic. Scoring is pure and unit-tested in
`tests/evals`; the live run needs `GROQ_API_KEY` and the embedding model.

### Deployment (`deploy/`, `Dockerfile`, `frontend/Dockerfile`)

Full guide: `deploy/README.md`. Two Terraform stacks: `deploy/ec2` (one host, Docker Compose + Caddy, EBS data
volume with daily snapshots, secrets in SSM Parameter Store) and `deploy/ecs` (CloudFront → ALB → Fargate, RDS,
Qdrant on a private EC2, S3 frontend, Secrets Manager; `deploy/ecs/deploy.sh` does build/push/apply/publish).
Rules baked into both: **one API instance only** (audit-chain lock and upload jobs are per process; ECS deploys
stop-then-start and `api_desired_count` is validated to 0/1), the embedding model is baked into the API image
(`HF_HUB_OFFLINE=1` at runtime), the frontend talks to the API same-origin at `/api` (the proxy strips the
prefix), `VITE_API_KEY` is public by construction. CI's `infra` job runs `terraform fmt/validate`, compose,
Caddyfile and Dockerfile checks. Terraform has never been applied against a real AWS account by the authors.

### Frontend (`frontend/src`)

React 19 + Vite + Tailwind 4, no router — `App.jsx` switches between views in `components/views/` via local
state. `api.js` wraps `fetch` (`apiFetch`: base URL + API key) and polls upload jobs. `sourceLabel.js` formats
"Section · Clause 4.2 · p. 7". `data/mockData.js` is for UI development without a backend.

## Known incomplete pieces

`scripts/generate_synthetic_data.py` is a placeholder (`raise NotImplementedError`; `tests/test_stubs.py`
asserts that). `app/db/seed_synthetic.py` is implemented; it only seeds an empty DB.

The live LLM + embedding path (`python -m evals.run_eval`) has not been run in CI or by the authors of the
latest hardening pass (no API key / model download in their environment) — run it before trusting accuracy.

## Conventions specific to this codebase

- Graph nodes are plain functions `(state: ComplianceState) -> dict` returning only the keys they change.
  Never mutate `state` in place.
- Env vars (`DATABASE_URL`, `QDRANT_URL`, `GROQ_*`, `API_KEYS`, `CORS_ORIGINS`, `MAX_UPLOAD_MB`, `LOG_LEVEL`,
  `ALLOW_MEMORY_CHECKPOINTER`, `QDRANT_API_KEY`) are read at the point of use with fallbacks matching `docker-compose.yml`.
  `.env` must be loaded (`load_dotenv()` in `app/api/main.py`) *before* `app.db.database` is imported.
- The LangGraph checkpointer **fails startup** if Postgres is unreachable; the in-memory fallback is only for
  SQLite URLs or an explicit `ALLOW_MEMORY_CHECKPOINTER=1`.
- Use `logging` (`logger = logging.getLogger(__name__)`), not `print`. Pipeline lines carry `stage=… thread=…`.
- Pure business logic (`compute_status`, `resolve_due_date`, `compute_audit_hash`, `verify_chain`,
  `split_into_clauses`, eval scoring) is dependency-free and tested directly. Anything touching Groq / Qdrant /
  Postgres is tested with mocks, an in-memory Qdrant (`QdrantClient(location=":memory:")`) or in-memory SQLite.
  Test files that need a DB override `get_db` with a `StaticPool` SQLite session (see `tests/api/test_main.py`).
- Postgres host port is `5433`, not `5432` — this machine has an unrelated Postgres on `5432` (see
  `docker-compose.yml`). Don't "fix" this back to 5432.
