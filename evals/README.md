# Evaluation harness

Measures how well the pipeline extracts obligations and classifies clause changes, and
how a confidence cutoff trades reviewer workload for accuracy.

```bash
export GROQ_API_KEY=...            # live LLM calls: ~40 per full run
python -m evals.run_eval           # both suites
python -m evals.run_eval --suite diff --out evals/results/run.json
```

* `data/extraction_cases.json` — 24 synthetic SEBI-stockbroker-style clauses with expected
  frequency / deadline rule / requirement keywords / evidence keywords. Cases marked
  `"hard": true` are ambiguous on purpose and are also reported separately.
* `data/diff_cases.json` — 16 prior-clause / new-clause pairs (4 each of new, unchanged,
  amended, superseded). The runner loads the prior clauses into an in-memory Qdrant and
  runs the real `differ_node`.
* The report includes a **confidence-threshold sweep**: for each cutoff, the share of clauses a
  human would review, the accuracy of the auto-accepted rest, and how many wrong answers slip
  through. Use it to choose the routing thresholds in `app/graph/build_graph.py`.

The clauses are synthetic, not quotations from real circulars; extend the JSON files with
real (anonymised) clauses as you collect them. Scoring is in `scoring.py` and is unit-tested
without any LLM (`tests/evals`).
