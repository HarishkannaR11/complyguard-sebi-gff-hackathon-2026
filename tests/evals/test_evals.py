import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.graph.nodes import ExtractedObligation
from evals import run_eval
from evals.scoring import (
    DIFF_LABELS, aggregate_extraction, confusion_matrix, diff_metrics, score_extraction, threshold_sweep,
)

DATA = Path(run_eval.__file__).parent / "data"
EXPECTED = {"frequency": "monthly", "deadline_rule": "monthly",
            "requirement_keywords": [["reconcil"], ["fund"]], "evidence_keywords": ["statement"]}


# ── dataset sanity ───────────────────────────────────────────────────────────

def test_extraction_dataset_is_well_formed():
    cases = json.loads((DATA / "extraction_cases.json").read_text())["cases"]
    assert len(cases) >= 20
    assert len({c["id"] for c in cases}) == len(cases)
    freqs = {"one-time", "monthly", "quarterly", "annual"}
    for c in cases:
        exp = c["expected"]
        assert c["clause"].strip()
        for f in (exp["frequency"] if isinstance(exp["frequency"], list) else [exp["frequency"]]):
            assert f in freqs, c["id"]
        deadline = exp["deadline_rule"]
        if deadline is not None:
            assert deadline in freqs or date.fromisoformat(deadline), c["id"]
        assert exp["requirement_keywords"] and all(exp["requirement_keywords"]), c["id"]
        assert exp["evidence_keywords"], c["id"]
    assert {"monthly", "quarterly", "annual", "one-time"} <= {
        (c["expected"]["frequency"] if isinstance(c["expected"]["frequency"], str) else c["expected"]["frequency"][0])
        for c in cases}


def test_diff_dataset_is_well_formed_and_balanced():
    cases = json.loads((DATA / "diff_cases.json").read_text())["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    by_label = {label: [c for c in cases if c["expected_status"] == label] for label in DIFF_LABELS}
    assert all(len(v) >= 3 for v in by_label.values()), {k: len(v) for k, v in by_label.items()}
    for c in cases:
        assert c["prior"] and all(p["obligation_id"] and p["text"] for p in c["prior"])


# ── scoring ──────────────────────────────────────────────────────────────────

def test_perfect_extraction_scores_all_true():
    actual = {"frequency": "Monthly", "deadline_rule": "monthly",
              "requirement": "Submit the monthly fund and securities Reconciliation", "evidence_type": "Statement copy"}
    assert score_extraction(EXPECTED, actual)["all"] is True


def test_null_and_one_time_deadlines_are_equivalent():
    exp = {**EXPECTED, "deadline_rule": None}
    for value in (None, "", "one-time"):
        assert score_extraction(exp, {"frequency": "monthly", "deadline_rule": value,
                                      "requirement": "fund reconciliation", "evidence_type": "statement"})["deadline_rule"]
    assert not score_extraction(exp, {"frequency": "monthly", "deadline_rule": "monthly",
                                      "requirement": "fund reconciliation", "evidence_type": "statement"})["deadline_rule"]


def test_expected_list_accepts_any_listed_frequency():
    exp = {**EXPECTED, "frequency": ["annual", "quarterly"]}
    base = {"deadline_rule": "monthly", "requirement": "fund reconciliation", "evidence_type": "statement"}
    assert score_extraction(exp, {**base, "frequency": "quarterly"})["frequency"]
    assert not score_extraction(exp, {**base, "frequency": "monthly"})["frequency"]


def test_every_requirement_keyword_group_must_match():
    actual = {"frequency": "monthly", "deadline_rule": "monthly", "requirement": "reconciliation only",
              "evidence_type": "statement"}
    assert not score_extraction(EXPECTED, actual)["requirement"]


def test_failed_extraction_scores_false_everywhere():
    assert score_extraction(EXPECTED, None) == {k: False for k in
        ("frequency", "deadline_rule", "requirement", "evidence_type", "all")}


def test_aggregate_extraction():
    scores = [score_extraction(EXPECTED, None),
              {"frequency": True, "deadline_rule": True, "requirement": True, "evidence_type": True, "all": True}]
    agg = aggregate_extraction(scores)
    assert agg["all"] == 0.5 and agg["frequency"] == 0.5


def test_diff_metrics_and_confusion_matrix():
    pairs = [("new", "new"), ("new", "amended"), ("amended", "amended"), ("unchanged", "unchanged")]
    metrics = diff_metrics(pairs)
    assert metrics["accuracy"] == 0.75
    assert metrics["labels"]["amended"] == {"precision": 0.5, "recall": 1.0, "support": 1}
    assert metrics["labels"]["superseded"]["precision"] is None
    assert confusion_matrix(pairs)["new"] == {"new": 1, "amended": 1}


def test_threshold_sweep_trades_review_load_for_accuracy():
    items = [(0.95, True), (0.9, True), (0.75, False), (0.6, False), (None, False)]
    rows = {r["threshold"]: r for r in threshold_sweep(items, [0.5, 0.8, 0.95])}
    assert rows[0.8]["auto_accepted"] == 2 and rows[0.8]["auto_accuracy"] == 1.0
    assert rows[0.8]["review_rate"] == 0.6
    assert rows[0.5]["errors_slipping_through"] == 2
    assert rows[0.95]["auto_accepted"] == 1


# ── runner end to end, with the LLM and embedder faked ───────────────────────

def _fake_extractor(state):
    return {"extracted_obligation": {
        "requirement": "Do the thing", "frequency": "annual", "evidence_type": "report",
        "deadline_rule": "annual", "deadline_confidence": 0.9, "entity_confidence": 0.9,
        "evidence_confidence": 0.9, "overall_confidence": 0.9}}


def test_run_extraction_counts_a_validation_failure_as_a_miss_not_a_crash():
    cases = [{"id": "x1", "clause": "c", "expected": {**EXPECTED}}]
    bad = {"extracted_obligation": {"requirement": "r", "frequency": "weekly", "evidence_type": "e",
                                    "deadline_rule": None, "deadline_confidence": 1, "entity_confidence": 1,
                                    "evidence_confidence": 1, "overall_confidence": 1}}
    with patch("app.graph.nodes.extractor_node", return_value=bad):
        report = run_eval.run_extraction(cases)
    assert report["overall"]["all"] == 0
    assert "ValidationError" in report["cases"][0]["error"]


def test_run_extraction_reports_sweep_and_hard_case_split():
    cases = json.loads((DATA / "extraction_cases.json").read_text())["cases"][:4]
    with patch("app.graph.nodes.extractor_node", side_effect=_fake_extractor):
        report = run_eval.run_extraction(cases)
    assert report["n"] == 4
    assert len(report["confidence_threshold_sweep"]) == len(run_eval.THRESHOLDS)
    assert all(r["confidence"] == 0.9 for r in report["cases"])
    ExtractedObligation(**report["cases"][0]["actual"])  # round-trips through the real validator


def test_run_diff_against_in_memory_qdrant_with_a_fake_llm():
    cases = json.loads((DATA / "diff_cases.json").read_text())["cases"][:2]

    def fake_embed(texts):
        return [[float(len(t) % 7), 1.0, float(len(t) % 3), 0.5] for t in texts]

    llm = '{"status": "NEW", "confidence": 0.9, "matched_obligation_id": null, "changes": [], "reason": "x"}'
    with patch("app.embeddings.embedder.embed_texts", side_effect=fake_embed), \
         patch("app.graph.nodes.chat_completion", return_value=llm):
        report = run_eval.run_diff(cases)
    assert report["n"] == 2
    assert [r["predicted"] for r in report["cases"]] == ["new", "new"]
    assert report["metrics"]["labels"]["new"]["recall"] == 1.0
    assert all(r["error"] is None for r in report["cases"])


def test_main_writes_a_json_report(tmp_path, capsys):
    out = tmp_path / "r.json"
    with patch("app.graph.nodes.extractor_node", side_effect=_fake_extractor):
        assert run_eval.main(["--suite", "extraction", "--out", str(out)]) == 0
    assert "Extraction (24 clauses)" in capsys.readouterr().out
    assert json.loads(out.read_text())["extraction"]["n"] == 24
