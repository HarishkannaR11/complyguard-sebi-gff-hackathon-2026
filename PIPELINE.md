# RegOps AI — Pipeline Implementation Documentation

This document describes, stage by stage, how a SEBI circular PDF becomes tracked, auditable
compliance obligations in RegOps AI. It is the implementation-level companion to `README.md` (product
framing) and `CLAUDE.md` (repo-level orientation for AI coding agents). Design rationale and the bug
fixes applied while wiring this together live in `docs/superpowers/specs/2026-07-22-langgraph-pipeline-design.md`
and `docs/superpowers/specs/2026-07-22-regops-ai-restructure-design.md` — this document describes the
system as it exists now, not the history of how it got there.

## 1. End-to-end flow

```
                     ┌─────────────────────────────────────────────────────────────────┐
                     │                     POST /upload (app/api/main.py)               │
                     └─────────────────────────────────────────────────────────────────┘
  PDF file
     │
     ▼
┌──────────────────┐
│  hybrid_parser   │───▶  for each structured chunk: run the LangGraph state
│  (PyMuPDF / block │      machine (app/graph/build_graph.py)
│  & table extraction)
└──────────────────┘
                                             │
                             ┌───────────────┴────────────────┐
                             │  per-chunk result:             │
                             │  processed / pending_review /  │
                             │  error                         │
                             └───────────────┬────────────────┘
                                             ▼
                                       ┌──────────────────────────────────────────┐
                                       │ mark_superseded_obligations()             │
                                       │ (app/services/supersession.py, batch-level,│
                                       │  only if zero clauses errored)            │
                                       └──────────────────────────────────────────┘
                                             │
                                             ▼
                                       response: {results[], superseded_obligation_ids[]}
```

Everything downstream of upload (`GET /obligations`, `GET /gaps`, `POST /evidence`,
`POST /review/{thread_id}/decision`, `GET /audit_log`) reads/writes the Postgres tables the graph
populated and the Qdrant collection it upserted into. There is no background worker — `POST /upload`
runs the whole per-clause pipeline synchronously inside the request.

## 2. Hybrid Document Parsing (`app/ingestion/hybrid_parser.py`)

Entry point: `parse_pdf_structured(pdf_path) -> list[dict]`.

This module acts as the primary layout-aware structure layer, extracting sections, subsections, clause numbering, parent-child relationships, page numbers, and tabular grids.

1. **Table Extraction**:
   - Opens the PDF with PyMuPDF and finds tables using `page.find_tables()`.
   - Table grids are extracted using `tab.extract()` and formatted into GFM (GitHub Flavored Markdown) representation to preserve grid structures.
   - The bounding box (`bbox`) of each table is kept to ensure their content is skipped in subsequent text block extraction, preventing duplicate reads.
2. **Text Block Layout Extraction**:
   - Uses PyMuPDF's block parser `page.get_text("blocks")` which yields reading-order sorted coordinate blocks.
   - Filters out text blocks that intersect with the bounding box of any detected tables.
   - Normalizes text spacing and removes boilerplate preamble text using routines defined in [pdf_cleaner.py](file:///home/krisharish/Documents/complyguard-sebi-gff-hackathon-2026/app/ingestion/pdf_cleaner.py).
3. **Hierarchy & Metadata Mapping**:
   - Identifies structural headers:
     - **Annexures**: Matched using regex e.g. `^Annexure\s+[A-Z0-9]+`.
     - **Sections**: Matched using Roman numerals `^([I|V|X|L|C|D|M]+)\.`.
     - **Subsections**: Matched using alphabetical items `^([A-Z])\.`.
     - **Clauses**: Matched using numeric hierarchies `^(\d+(?:\.\d+)*)\.?\s+\S`.
   - Computes parent-child relations: a dotted decimal clause number (e.g. `3.2.1`) has its parent mapped as its prefix (e.g. `3.2`).
4. **Segmentation Confidence Score**:
   - Assigns a confidence value to each chunk to enforce reliability guidelines:
     - Clause numbers (`0.95`)
     - Table grids (`0.90`)
     - Structural boundaries/annexures (`0.90`)
     - Continuation text blocks under an active clause (`0.85`)
     - Unstructured body text / fallback splits (`0.50`)
     - Orphans/short fragments (`0.65` / `0.60`)
5. **Legacy Fallback**:
   - If PyMuPDF throws errors (e.g. corrupted PDF binary, or mock test streams containing dummy headers), the parser catches the error and runs the legacy `extract_and_clean` + `split_into_clauses` routines, packaging them into uniform dictionary structures (with low confidence to flag them for human review).

## 4. Stage 3 — The per-clause LangGraph pipeline

### 4.1 State shape (`app/graph/state.py`)

```python
class ComplianceState(TypedDict):
    circular_id: str
    clause_id: str
    raw_clause: str
    heading: str
    embedding: Optional[List[float]]
    extracted_obligation: Optional[dict]
    similarity_match: Optional[dict]
    diff_status: Literal["new", "amended", "superseded", "unchanged", None]
    task: Optional[dict]
    evidence_status: Literal["present", "missing", "invalid", None]
    human_decision: Optional[str]
    audit_log: List[dict]
```

Every node is a plain function `(state) -> dict` that returns **only the keys it changes** — LangGraph
merges partial updates into the running state rather than requiring nodes to return the full state.
No node mutates `state` in place.

### 4.2 Graph wiring (`app/graph/build_graph.py`)

```
chunker → embedder → extractor → differ ─┬─(new)──────────────────┐
                                          ├─(amended/superseded)→ human_review ─┐
                                          └─(unchanged)──────────────────────┐  │
                                                                              │  │
                              ┌───────────────────────────────────────────┐  │  │
                              │                                           ▼  ▼  │
                                                                        mapper  │
                                                                           │    │
                                                                           ▼    │
                                                                    evidence_check
                                                                     │    │    │
                                                          (present)──┘    │    └─(missing)
                                                                          │         │
                                                                     (invalid)       ▼
                                                                          │    gap_engine
                                                                          ▼         │
                                                                   human_review      │
                                                                          │         │
                                                              (loops back to mapper) │
                                                                                     ▼
                                                                                 finalize → END
```

Routing functions:
- `route_after_diff(state)`: `"amended"`/`"superseded"` → `human_review`; `"unchanged"` → `finalize`
  directly (nothing to map or check evidence for — no duplicate `Task` should be created for a clause
  that hasn't changed); anything else (`"new"`) → `mapper`.
- `route_after_evidence(state)`: `"missing"` → `gap_engine`; `"invalid"` → `human_review`; otherwise
  (`"present"`) → `finalize`.

The graph is compiled with a **Postgres-backed checkpointer** (`langgraph.checkpoint.postgres.PostgresSaver`),
built lazily as a module-level singleton the first time `build_graph()` runs (via
`contextlib.ExitStack`, held open for the process's lifetime — acceptable for this app's
single-process deployment, not safe to assume in a multi-process/serverless deployment without
revisiting). `.setup()` is called once to create the checkpoint tables. Each clause run is invoked
with `config={"configurable": {"thread_id": f"{circular_id}:{clause_id}"}}` — this `thread_id` is the
handle that later lets a paused run be resumed by exactly matching thread.

### 4.3 Nodes in detail (`app/graph/nodes.py`)

**`chunker_node`** — pure, no I/O. Strips `raw_clause`; derives `heading` from the clause's first line
(truncated to 80 chars) if the caller didn't already supply one.

**`embedder_node`** — calls `app.embeddings.embedder.embed_texts([raw_clause])[0]` (see §5) to produce
a 768-dim embedding vector for the clause.

**`extractor_node`** — calls Groq (`llama-3.3-70b-versatile` by default, overridable via `GROQ_MODEL`)
with a fixed prompt (`EXTRACTION_PROMPT`) asking for one JSON object:
```json
{
  "requirement": "Clear description of what must be done",
  "frequency": "one-time | monthly | quarterly | annual | ...",
  "evidence_type": "What proof is needed",
  "deadline_rule": "ISO date, a frequency keyword, or null"
}
```
`temperature=0`, `max_tokens=800`. Retries up to `MAX_RETRIES = 3` times with `1.5 * attempt` second
backoff on `groq.APIConnectionError` only (other errors propagate immediately). The response is
stripped of Markdown code fences and the first/last `{`/`}` are used to isolate the JSON object before
`json.loads`, tolerating models that wrap JSON in prose despite the instruction not to.

**`differ_node`** — read-only. Implements the two-stage semantic comparison pipeline:
- **Stage 1 (Retrieval)**: Queries the Qdrant collection for the top-3 nearest candidate clauses based on the embedding of the current clause. If no candidates are found, it skips the LLM step and classifies it as `"new"`.
- **Stage 2 (LLM Comparison)**: Formats candidates alongside the new clause text and sends a prompt (`COMPARISON_PROMPT`) to the Groq LLM (e.g. `llama-3.3-70b-versatile`). The LLM evaluates semantic matches, returning a structured JSON object containing:
  - `status`: `"NEW"`, `"AMENDED"`, `"SUPERSEDED"`, or `"UNCHANGED"`.
  - `confidence`: Confidence score (`0.0` - `1.0`).
  - `matched_obligation_id`: The ID of the matching candidate from older circulars.
  - `changes`: List of modified fields (e.g. `["deadline"]`).
  - `reason`: Explanation of comparison details.
- **Auditing**: Records comparison results (status, changes, reasons, confidence) in the `AuditTrail` table by calling `_write_audit_entry` with `node_name="differ"`.
- **Normalization**: Maps uppercase LLM status back to lowercase `diff_status` (`"new"`, `"amended"`, `"superseded"`, `"unchanged"`) and resolves `similarity_match` to the corresponding candidate hit, ensuring full downstream compatibility.

**`human_review_node`** — reached only on `"amended"`/`"superseded"` (from `differ`) or `"invalid"`
(from `evidence_check`). Calls `langgraph.types.interrupt({...})` with the clause id, extracted
obligation, diff status, and similarity match — this **pauses graph execution** and returns control to
the caller. `app/api/routes_review.py`'s `POST /review/{thread_id}/decision` resumes it via
`Command(resume={"decision": decision, "actor": actor})`; that dict becomes `human_review_node`'s
return value from `interrupt(...)` when the graph resumes. Decisions:
- `"approve"` — `extracted_obligation` unchanged.
- `"reject"` — `human_decision = "reject"`; checked by `mapper_node` to skip persisting anything.
- `"amend:<json>"` — the JSON suffix is parsed and shallow-merged into `extracted_obligation`;
  `human_decision` is normalized to `"amend"`.

Writes one `AuditTrail` row (`node_name="human_review"`, `actor` from the resume payload) recording the
decision before returning.

**`mapper_node`** — no-op (returns `{}`) if `human_decision == "reject"` or `diff_status ==
"unchanged"`. Otherwise:
1. Resolves which `Obligation` row to write: for `"amended"`, look up
   `similarity_match["payload"]["obligation_id"]` in Postgres; if found, update it in place. Otherwise
   (including all `"new"` clauses) insert a fresh `Obligation` (`uuid4` id).
2. Sets `requirement` / `frequency` / `evidence_type` / `deadline_rule` from `extracted_obligation`.
3. Resolves a concrete due date via `resolve_due_date(deadline_rule, today)`: an ISO date string is
   parsed directly; a recognized frequency keyword (`monthly`/`quarterly`/`annual`, via
   `FREQUENCY_DAYS = {30, 90, 365}` days) becomes `today + N days`; anything else (including `None`,
   open-ended obligations) resolves to `None`.
4. Creates a `Task` row (`uuid4` id, `owner="compliance"`, the resolved `due_date`).
5. Upserts the clause's embedding into Qdrant with `{circular_id, clause_id, obligation_id}` in the
   payload — this is what makes the `obligation_id` resolvable from a future `differ_node` match, and
   what `find_by_obligation_id()` uses later to recover the source clause for traceability.

Returns `{"task": {"id", "obligation_id", "due_date"}}`.

**`evidence_node`** — if `mapper_node` produced no `task` (i.e. it no-opped), returns
`evidence_status = "missing"` immediately. Otherwise queries `EvidenceLog` for any row against this
`task.id`: present → `"present"`, none → `"missing"`. `"invalid"` is a reserved value for a future
validation rule (e.g. evidence that doesn't match the required `evidence_type`) — **not implemented
yet**; this node never returns it today.

**`gap_engine_node`** — reached only when evidence is `"missing"`. Loads the `Task`, computes its
`status` via `app.services.gap_engine.compute_status(has_evidence=False, deadline, today)`, persists it.

**`finalize_node`** — always runs last (from either `evidence_check`'s `"present"` branch, from
`gap_engine`, or directly from `differ`'s `"unchanged"` branch). Writes exactly one `AuditTrail` row
per graph run, `actor="system"`, summarizing `{obligation_id, task_id, diff_status, human_decision}`.
This is the hash-chain anchor — see §6.

## 5. Stage 4 — Embeddings and vector storage

**`app/embeddings/embedder.py`** wraps `sentence-transformers`' `BAAI/bge-base-en-v1.5` (768-dim,
local — no external API call, no API key). Models are cached in a module-level dict keyed by model
name (`_model_cache`) so repeated calls in the same process don't reload the model. `embed_texts([])`
returns `[]` without touching the model.

**`app/embeddings/qdrant_client.py`** wraps the Qdrant Python client against a single collection,
`circular_clauses` (cosine distance, 768-dim, created on first use via `ensure_collection`).

- `upsert_chunks(client, chunks, vectors, metadatas)` — one point per chunk, payload =
  `{**metadata, "text": chunk}`, point id a fresh `uuid4`.
- `search(client, query_vector, limit=3)` — returns `[{text, score, payload}]` per hit (the `payload`
  key is an additive, backward-compatible extension — earlier callers that only read `text`/`score`
  are unaffected).
- `find_by_obligation_id(client, obligation_id)` — a payload-filtered `scroll` (not a vector search)
  used purely for traceability lookups (`GET /obligations`'s `source_chunk` field), not for diffing.

## 6. Stage 5 — Persistence (`app/db/`)

**`app/db/database.py`** — one SQLAlchemy `Base` (`declarative_base()`), one `engine`/`SessionLocal`
pair against `DATABASE_URL` (default `postgresql://regops:regops@localhost:5433/regops`, matching
`docker-compose.yml`'s host-port remap — see the compose file's comment on why it's 5433 not 5432).
`get_db()` is the FastAPI dependency; every non-FastAPI call site (graph nodes, services) opens its
own `SessionLocal()` and closes it in a `finally` block.

**`app/db/models.py`** — imports `Base` from `database.py` (not a second `declarative_base()`) so
`Base.metadata.create_all()` in `app/api/main.py`'s lifespan hook picks up all four tables:

| Table | Purpose | Key columns |
|---|---|---|
| `obligations` | one row per distinct compliance requirement | `id`, `clause_id`, `requirement`, `frequency`, `evidence_type`, `deadline_rule`, `status` (active/superseded) |
| `tasks` | the trackable instance of an obligation | `id`, `obligation_id` (FK), `owner`, `due_date`, `status` (pending/met/overdue) |
| `evidence_log` | proof attached against a task | `id`, `task_id` (FK), `file_ref`, `submitted_at` |
| `audit_trail` | immutable, hash-chained action log | `id`, `thread_id`, `node_name`, `action` (JSON), `actor`, `timestamp`, `prev_hash`, `hash` |

**Audit hash chain**: `compute_audit_hash(prev_hash, action, timestamp) = sha256(prev_hash +
json.dumps(action, sort_keys=True) + timestamp.isoformat())`. Every `_write_audit_entry()` call reads
the most recent existing row's `hash` as its own `prev_hash` before computing and committing the new
row — so tampering with any historical row's `action` breaks every subsequent row's hash when
recomputed, which is what makes the trail tamper-evident. **Known limitation** (documented inline in
`nodes.py`): this read-latest-then-commit sequence is not concurrency-safe — two writers committing
at the same instant can both read the same "latest" row and fork the chain. Acceptable for this app's
current single-request-at-a-time usage; a real fix needs row-level locking (`SELECT ... FOR UPDATE` on
the tail row) or a single serialized writer, deliberately not implemented.

**`app/services/gap_engine.py`** — `compute_status(has_evidence, deadline, today)` is the single pure
function all status decisions run through: evidence present → `"met"`; no evidence and `deadline <
today` → `"overdue"`; otherwise → `"pending"`. `update_all_task_statuses(db)` recomputes every task not
already `"met"` against today's date (skips tasks already `"met"` — evidence, once submitted, is
final). `get_gaps(db)` calls that recompute first, then returns every `Task` with status `pending` or
`overdue`.

**`app/services/supersession.py`** — `mark_superseded_obligations(db, circular_id,
matched_obligation_ids)` is a **batch-level**, not per-clause, concern: after all of a circular's
clauses have been run through the graph, any currently-`"active"` obligation whose id isn't in the set
of obligations matched during this upload gets marked `"superseded"`. Called from `app/api/main.py`'s
`/upload` handler, and only when zero clauses in the batch errored — a partial run can't be trusted to
say "this obligation's clause is genuinely gone" rather than "its clause failed to process."

## 7. Stage 6 — API surface (`app/api/main.py`, `app/api/routes_review.py`)

| Endpoint | Behavior |
|---|---|
| `GET /health` | liveness check |
| `POST /upload` | saves the PDF to `data/raw_pdfs/`, runs stages 1–5 for every clause synchronously, runs supersession detection, returns per-clause outcomes (`processed` / `pending_review` / `error`) plus `superseded_obligation_ids` |
| `GET /obligations` | recomputes task statuses, then joins each active `Obligation` to its `Task` and Qdrant-sourced `source_chunk` for the dashboard/traceability view |
| `GET /gaps` | `pending`/`overdue` tasks only |
| `GET /evidence` | all evidence rows, joined back to their obligation |
| `POST /evidence` | attaches an `EvidenceLog` row to the `Task` for a given `obligation_id` (404 if no task exists yet) |
| `GET /audit_log` | full audit trail, newest first, with node names mapped to display labels via `_AUDIT_ACTION_LABELS` |
| `POST /review/{thread_id}/decision` | resumes a paused `human_review` interrupt; **rejects with 409** if the thread isn't actually paused (`Command(resume=...)` on a non-paused/nonexistent thread is otherwise a silent no-op that would look like success) |

`/upload`'s per-clause loop tracks `matched_obligation_ids` from three sources: a completed run's
`task.obligation_id`, an `"unchanged"` clause's `similarity_match` (mapper no-oped but the obligation
is still current), and a `pending_review` clause's `similarity_match` (protects an obligation awaiting
a human decision from being wrongly superseded before that decision is made).

## 8. Stage 7 — Frontend (`frontend/src`)

Plain React 19 + Vite + Tailwind 4, no router. `App.jsx` switches between views by local state:
`Landing` / `Hero` → `UploadCircular` → `ObligationList` / `GapDashboard` / `AuditTrail`. `api.js` is a
thin `fetch` wrapper hardcoded to `http://localhost:8000`, one function per backend endpoint listed in
§7. `data/mockData.js` supports UI development without a live backend running.

## 9. Running the pipeline manually (debugging / demo)

```bash
# 1. infra
docker compose up -d

# 2. ingest-only (Qdrant, no LLM, no Postgres writes) — useful for pre-seeding the vector store
python -m scripts.run_ingest data/raw_pdfs/<circular>.pdf

# 3. full per-clause pipeline (Groq + Postgres + Qdrant) over one clause
python -m scripts.run_diff <circular_id> <clause_id> '<raw clause text>'

# 4. or drive the whole thing through the API as the frontend does
uvicorn app.api.main:app --reload --port 8000
curl -F file=@data/raw_pdfs/<circular>.pdf http://localhost:8000/upload

# 5. resume a paused human-review thread (thread_id = "<circular_id>:<clause_id>")
curl -X POST "http://localhost:8000/review/<circular_id>:<clause_id>/decision?decision=approve&actor=jane"
```

## 10. Testing strategy

Mirrors the pipeline's own layering:
- **Pure logic** (`compute_status`, `resolve_due_date`, `compute_audit_hash`, `split_into_clauses`,
  `chunker_node`) — real unit tests, no mocking (`tests/services/`, `tests/ingestion/`,
  `tests/graph/test_nodes.py`).
- **External-service-touching code** (Groq calls, Qdrant client, Postgres-backed nodes) — tested via
  mocks (`MagicMock`-based, see `tests/embeddings/test_qdrant_client.py` and the extractor/differ/
  mapper tests in `tests/graph/`), not live services.
- **Graph shape** — `build_graph()` is tested by injecting an in-memory checkpointer
  (`langgraph.checkpoint.memory.MemorySaver`) to confirm it compiles and edges route correctly, not by
  running a full live end-to-end pass.
- **API routes** — `tests/api/` exercises FastAPI's `TestClient` against a mocked DB session/graph.

Run everything: `python -m pytest`. Run one area: `python -m pytest tests/graph/`.

## 11. Known incomplete pieces

- `app/db/seed_synthetic.py` and `scripts/generate_synthetic_data.py` are placeholder stubs
  (`raise NotImplementedError`) — the intended output (6 obligations, 143 tasks, 129 evidence rows, 25
  grievances, org roles) is documented in their docstrings but not yet implemented.
- `evidence_status = "invalid"` is a reserved state in `ComplianceState` and routed in the graph, but
  no node currently produces it — evidence validation logic doesn't exist yet.
- OCR for scanned/image PDF pages is flagged (`[WARN]` in `pdf_cleaner.extract_pages`) but not
  implemented; such pages silently contribute near-empty text to the pipeline.
- The audit-hash-chain write path is not safe under concurrent writers (§6).
- No authentication/authorization on any endpoint, including `POST /review/{thread_id}/decision`.
