"""Pure scoring helpers for the extraction / diff evaluation (no I/O, no LLM)."""
from collections import Counter

DIFF_LABELS = ["new", "unchanged", "amended", "superseded"]


def _norm_deadline(value):
    """None, "" and the bare "one-time" keyword all mean 'no concrete deadline'."""
    if value is None:
        return None
    value = str(value).strip().lower()
    return None if value in ("", "one-time", "null", "none") else value


def _as_list(expected):
    return list(expected) if isinstance(expected, (list, tuple)) else [expected]


def _contains_any(text: str, needles: list[str]) -> bool:
    text = (text or "").lower()
    return any(n.lower() in text for n in needles)


def score_extraction(expected: dict, actual: dict | None) -> dict:
    """Per-field correctness for one extraction. ``actual`` None means the pipeline failed."""
    if not actual:
        return {"frequency": False, "deadline_rule": False, "requirement": False,
                "evidence_type": False, "all": False}

    frequency_ok = str(actual.get("frequency", "")).strip().lower() in [
        str(f).lower() for f in _as_list(expected["frequency"])
    ]
    deadline_ok = _norm_deadline(actual.get("deadline_rule")) in [
        _norm_deadline(d) for d in _as_list(expected["deadline_rule"])
    ]
    requirement_ok = all(
        _contains_any(actual.get("requirement", ""), group)
        for group in expected["requirement_keywords"]
    )
    evidence_ok = _contains_any(actual.get("evidence_type", ""), expected["evidence_keywords"])
    return {
        "frequency": frequency_ok,
        "deadline_rule": deadline_ok,
        "requirement": requirement_ok,
        "evidence_type": evidence_ok,
        "all": frequency_ok and deadline_ok and requirement_ok and evidence_ok,
    }


def aggregate_extraction(scores: list[dict]) -> dict:
    n = len(scores) or 1
    return {k: sum(1 for s in scores if s[k]) / n for k in
            ("frequency", "deadline_rule", "requirement", "evidence_type", "all")}


def confusion_matrix(pairs: list[tuple[str, str]]) -> dict:
    """pairs = [(expected, predicted)] -> {expected: {predicted: count}}"""
    matrix = {e: Counter() for e in DIFF_LABELS}
    for expected, predicted in pairs:
        matrix.setdefault(expected, Counter())[predicted] += 1
    return {e: dict(c) for e, c in matrix.items()}


def diff_metrics(pairs: list[tuple[str, str]]) -> dict:
    """Accuracy plus per-label precision/recall."""
    total = len(pairs) or 1
    metrics = {"accuracy": sum(1 for e, p in pairs if e == p) / total, "labels": {}}
    for label in DIFF_LABELS:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        predicted = sum(1 for _, p in pairs if p == label)
        actual = sum(1 for e, _ in pairs if e == label)
        metrics["labels"][label] = {
            "precision": tp / predicted if predicted else None,
            "recall": tp / actual if actual else None,
            "support": actual,
        }
    return metrics


def threshold_sweep(items: list[tuple[float | None, bool]], thresholds: list[float]) -> list[dict]:
    """How a confidence cutoff trades human workload against accuracy.

    items: [(model_confidence, was_correct)]. Clauses below the threshold go to a human;
    the rest are auto-accepted. ``auto_accuracy`` is the accuracy of the auto-accepted set
    (the errors that would slip through unreviewed).
    """
    rows = []
    total = len(items) or 1
    for threshold in thresholds:
        auto = [ok for conf, ok in items if conf is not None and conf >= threshold]
        rows.append({
            "threshold": threshold,
            "review_rate": 1 - len(auto) / total,
            "auto_accepted": len(auto),
            "auto_accuracy": (sum(auto) / len(auto)) if auto else None,
            "errors_slipping_through": sum(1 for ok in auto if not ok),
        })
    return rows
