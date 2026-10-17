"""Run the extraction and diff evaluations against the real pipeline nodes.

    python -m evals.run_eval                 # both suites, needs GROQ_API_KEY + the embedding model
    python -m evals.run_eval --suite diff    # just one
    python -m evals.run_eval --out evals/results/run.json

Uses an in-memory Qdrant and does not touch Postgres. Calls the live Groq API, so it costs
a few dozen requests per run.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

from evals.scoring import (
    aggregate_extraction, confusion_matrix, diff_metrics, score_extraction, threshold_sweep,
)

DATA_DIR = Path(__file__).parent / "data"
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]


def load_cases(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text())["cases"]


def run_extraction(cases: list[dict]) -> dict:
    from app.graph.nodes import ExtractedObligation, extractor_node

    rows, scores, sweep_items = [], [], []
    for case in cases:
        actual, error, confidence = None, None, None
        try:
            raw = extractor_node({"raw_clause": case["clause"], "circular_id": "eval", "clause_id": case["id"]})
            actual = raw["extracted_obligation"]
            validated = ExtractedObligation(**actual)  # same validation the pipeline applies
            actual = validated.model_dump()
            confidence = validated.overall_confidence
        except Exception as exc:  # a failed/invalid extraction counts as wrong, not as a crash
            error = f"{type(exc).__name__}: {exc}"
        score = score_extraction(case["expected"], actual)
        scores.append(score)
        sweep_items.append((confidence, score["all"]))
        rows.append({"id": case["id"], "hard": case.get("hard", False), "score": score,
                     "confidence": confidence, "actual": actual, "error": error})

    easy = [s for s, c in zip(scores, cases) if not c.get("hard")]
    return {
        "n": len(cases),
        "overall": aggregate_extraction(scores),
        "excluding_hard_cases": aggregate_extraction(easy),
        "confidence_threshold_sweep": threshold_sweep(sweep_items, THRESHOLDS),
        "cases": rows,
    }


def run_diff(cases: list[dict]) -> dict:
    from app.embeddings import qdrant_client as qc
    from app.embeddings.embedder import embed_texts
    from app.graph.nodes import differ_node

    pairs, rows, sweep_items = [], [], []
    for case in cases:
        qc.reset_clients()
        client = qc.get_client(":memory:")
        vectors = embed_texts([p["text"] for p in case["prior"]])
        qc.ensure_collection(client, vector_size=len(vectors[0]))
        qc.upsert_chunks(
            client, [p["text"] for p in case["prior"]], vectors,
            [{"circular_id": "old", "clause_id": f"c{i}", "obligation_id": p["obligation_id"]}
             for i, p in enumerate(case["prior"])],
        )
        predicted, confidence, error = "error", None, None
        try:
            with patch("app.graph.nodes._write_audit_entry"):  # no Postgres in the eval
                out = differ_node({
                    "circular_id": "new", "clause_id": case["id"], "raw_clause": case["clause"],
                    "embedding": embed_texts([case["clause"]])[0],
                })
            predicted, confidence = out["diff_status"], out.get("diff_confidence")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        pairs.append((case["expected_status"], predicted))
        sweep_items.append((confidence, predicted == case["expected_status"]))
        rows.append({"id": case["id"], "expected": case["expected_status"], "predicted": predicted,
                     "confidence": confidence, "error": error})
    qc.reset_clients()
    return {
        "n": len(cases),
        "metrics": diff_metrics(pairs),
        "confusion_matrix": confusion_matrix(pairs),
        "confidence_threshold_sweep": threshold_sweep(sweep_items, THRESHOLDS),
        "cases": rows,
    }


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def print_report(report: dict) -> None:
    if "extraction" in report:
        e = report["extraction"]
        print(f"\n== Extraction ({e['n']} clauses) ==")
        for scope in ("overall", "excluding_hard_cases"):
            o = e[scope]
            print(f"  {scope:22s} all={_pct(o['all'])} freq={_pct(o['frequency'])} "
                  f"deadline={_pct(o['deadline_rule'])} req={_pct(o['requirement'])} evid={_pct(o['evidence_type'])}")
        print("  confidence cutoff -> review rate / accuracy of auto-accepted / errors slipping through")
        for r in e["confidence_threshold_sweep"]:
            print(f"    >= {r['threshold']:.2f}: review {_pct(r['review_rate'])}, "
                  f"auto-accuracy {_pct(r['auto_accuracy'])}, slipped {r['errors_slipping_through']}")
        for c in e["cases"]:
            if not c["score"]["all"]:
                print(f"    miss {c['id']}: {c['error'] or {k: v for k, v in c['score'].items() if not v}}")
    if "diff" in report:
        d = report["diff"]
        print(f"\n== Diff ({d['n']} pairs) == accuracy {_pct(d['metrics']['accuracy'])}")
        for label, m in d["metrics"]["labels"].items():
            print(f"  {label:11s} precision={_pct(m['precision'])} recall={_pct(m['recall'])} n={m['support']}")
        print("  confusion (expected -> predicted):")
        for expected, row in d["confusion_matrix"].items():
            print(f"    {expected:11s} {row}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=["extraction", "diff", "all"], default="all")
    parser.add_argument("--out", help="write the full JSON report here")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    report = {}
    if args.suite in ("extraction", "all"):
        report["extraction"] = run_extraction(load_cases("extraction_cases.json"))
    if args.suite in ("diff", "all"):
        report["diff"] = run_diff(load_cases("diff_cases.json"))
    print_report(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nfull report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
