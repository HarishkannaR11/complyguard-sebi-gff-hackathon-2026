# Changelog — RegOps AI Version 2 Upgrades

This changelog records the upgrades delivered during the compliance pipeline V2 restructures.

---

## [V2.0.0] — 2026-07-31

### Added
- **Intelligent Layout-Aware Parser**: Coordinate-based layout and table grid block parser extracting sections, subsections, clause numbers, and GFM markdown tables using PyMuPDF.
- **Two-Stage Semantic Diff**: Stage 1 candidate retrieval from Qdrant followed by Stage 2 classification (NEW, AMENDED, SUPERSEDED, UNCHANGED) using Groq.
- **Confidence-Aware Validation Node**: Pydantic validations for extracted fields, automatic approvals (>=95%), warning flags (80-95%), and human review redirects (<80%).
- **State Machine Retry Loop**: Automated loop routing to retry LLM extractions once if validation fails.
- **Lineage Database Models**: Introduced relational mapping models for `Circular`, `Section`, `Clause`, `Deadline`, `ApplicableEntity`, and `Evidence`.
- **Review Queue Table**: Created `ReviewQueue` DB table storing visual HTML diffs, LLM logs, and review statuses.
- **Asynchronous Review API**: Non-blocking `BackgroundTasks` resume endpoint to asynchronously process review items.
- **Review Workspace View**: Side-by-side clause card layout in React with HTML diff highlighting, editing forms, and async submit controls.
- **Observability Exporters**: Centralized latency metrics collection exposing standard Prometheus text scraping and JSON metrics.
- **Backend Health Check**: Deep status probe verifying live PostgreSQL and Qdrant backend connectivity.
- **Advanced Dashboard**: Added compliance scores, critical tasks trackers, upcoming deadlines list, department breakdowns, and export to CSV / Excel buttons.

### Fixed
- **Legacy Fallback Compatibility**: Configured upload routes and scripts to fall back to legacy cleaning and splitting if PyMuPDF load errors occur or dummy unit tests mock the pipeline.
- **Deprecation Warnings**: Resolved all `utcnow()` deprecation warnings in active files and database seeds.
- **Missing Relationships**: Fixed ORM traversal attributes resolving clause to section joins.
- **State Keys**: Resolved KeyError crashes in tests on omitted Raw Clause parameters.
- **Section Parsing**: Fixed paragraph grouping logic ensuring clause headers within single blocks are correctly matched.
