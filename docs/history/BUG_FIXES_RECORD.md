# RegOps AI — Bug Fixes & Feature Additions Record

This document records the design and details of the critical bugs fixed and the features added in the backend pipeline to enable correct PDF uploading, processing, multi-user safety, and company obligations importing.

---

## 1. Resolved Issues

### 🔴 Issue A: Event Loop Blocking during Upload
- **Problem**: The `/upload` endpoint was defined as `async def`. But it executed heavily CPU-bound PDF parsing and sequential network/LLM calls in a loop. This completely blocked FastAPI's event loop, making the server freeze and become unresponsive to other API requests or health checks during processing.
- **Fix**: Changed the `/upload` endpoint signature to a standard synchronous `def` in `app/api/main.py`. FastAPI natively executes synchronous functions on a background thread pool, preventing it from blocking the main event loop.

### 🔴 Issue B: LangGraph interrupts Swallowed as Errors
- **Problem**: During a pipeline run, if a clause matched a previously seen obligation and requested review, LangGraph's `interrupt()` raised a `GraphInterrupt` exception. The catch-all `except Exception` in `/upload` treated this as a standard execution error, aborted the node, and failed the clause, bypassing the human-in-the-loop review registry.
- **Fix**: Added explicit handling for `GraphInterrupt` from `langgraph.errors` in `app/api/main.py`. The pipeline now catches the interrupt, updates the clause status to `"pending_review"`, preserves similarity matches, and continues processing other clauses.

### 🔴 Issue C: SQLite Multi-Thread Safety
- **Problem**: SQLite by default blocks multi-threaded database transactions, causing database crashes under async FastAPI threads or background workers.
- **Fix**: Configured the SQLAlchemy builder in `app/db/database.py` to pass `connect_args={"check_same_thread": False}` when the connection URL starts with `sqlite`.

### 🔴 Issue D: Concurrency Race Condition in Audit Trail
- **Problem**: Writing to the audit log used a non-isolated `read-latest-then-commit` sequence to compute the hash chain. Concurrent writers could read the same last block, leading to duplicate previous hashes (forking the chain) and defeating tamper-evidence verification.
- **Fix**: Secured `_write_audit_entry` in `app/graph/nodes.py` by enclosing it in a process-wide `threading.Lock` and using SQLAlchemy's `.with_for_update()` row-level database locking to guarantee atomic serialization.

### 🔴 Issue E: Unhandled GraphInterrupt in Review Resume Route
- **Problem**: Resubmitting a reviewer decision (`POST /review/{thread_id}/decision`) calls `graph.invoke()` to resume the thread. If the pipeline hits a subsequent interrupt (e.g. invalid evidence), `graph.invoke` raises a `GraphInterrupt`. Lacking exception handling, this returned a `500 Internal Server Error` to the client.
- **Fix**: Wrapped the resume invocation in `app/api/routes_review.py` in a try-except block to catch `GraphInterrupt`, returning a clean `{"status": "resumed_pending"}` status and state data to the client.

### 🔴 Issue F: Fragile LLM JSON Parser
- **Problem**: The `extractor_node` used a strict JSON loader. If the LLM returned extra conversational text or formatting anomalies (like trailing commas before braces), `json.loads` would throw a syntax error.
- **Fix**: Implemented a robust parser helper `parse_json_robust` in `app/graph/nodes.py` that strips formatting markers, matches the outer JSON block boundaries, and uses regex fallbacks to clean up trailing commas.

---

## 2. Added Features

### 🟢 Feature A: Import Company Obligations Checklist (CSV)
- **Design Intent**: Allows intermediaries to instantly upload and seed their existing internal compliance obligations spreadsheets into RegOps AI, bypassing the LLM PDF splitter.
- **Implementation**:
  - **Backend**: Added a `/import/obligations` endpoint to `app/api/main.py`. This reads an uploaded CSV, parses it row-by-row, and inserts corresponding records into the `Obligation` and `Task` database tables. If deadlines or dates are not provided, it resolves them using standard frequency rules.
  - **Frontend API**: Added `importObligationsCsv(file)` inside `frontend/src/api.js`.
  - **Frontend UI**: Integrated a new upload drop-zone section **"Import Company Obligations Checklist (CSV)"** inside `UploadCircular.jsx`. The UI visually aligns with the main dashboard style and successfully submits CSV uploads to the backend.
