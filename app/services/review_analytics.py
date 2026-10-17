"""Reviewer analytics: how often humans overrode the model, by confidence band."""
from typing import Iterable

# (label, inclusive lower bound, exclusive upper bound)
BANDS = [("low (<0.50)", 0.0, 0.5), ("medium (0.50-0.80)", 0.5, 0.8), ("high (>=0.80)", 0.8, 1.01)]
_RESOLVED = {"approved", "rejected", "edited"}


def _rate(num: int, den: int):
    return num / den if den else None


def summarize_reviews(items: Iterable) -> dict:
    """``items`` are ReviewQueue-like objects with ``status`` and ``confidence``.

    An *override* is a reviewer rejecting or editing what the model produced. A high
    override rate in a high-confidence band means the confidence cutoff is too lenient.
    """
    items = list(items)
    pending = sum(1 for i in items if i.status == "pending")
    resolved = [i for i in items if i.status in _RESOLVED]

    def band_stats(subset):
        approved = sum(1 for i in subset if i.status == "approved")
        rejected = sum(1 for i in subset if i.status == "rejected")
        edited = sum(1 for i in subset if i.status == "edited")
        total = len(subset)
        return {
            "reviewed": total, "approved": approved, "rejected": rejected, "edited": edited,
            "override_rate": _rate(rejected + edited, total),
        }

    bands = []
    for label, low, high in BANDS:
        subset = [i for i in resolved if i.confidence is not None and low <= i.confidence < high]
        bands.append({"band": label, **band_stats(subset)})
    unscored = [i for i in resolved if i.confidence is None]

    return {
        "pending": pending,
        "overall": band_stats(resolved),
        "by_confidence_band": bands,
        "unscored": band_stats(unscored) if unscored else None,
    }
