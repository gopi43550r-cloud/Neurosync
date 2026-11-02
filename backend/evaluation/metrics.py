"""Binary classification metrics used by the NeuroSync evaluation harness.

Deliberately small and dependency-free so the metric definitions are explicit
and auditable. Rates with an undefined denominator (e.g. recall when there are
no positive examples) are reported as ``None`` rather than an invented number.
"""
from __future__ import annotations


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def compute_binary_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """Compute confusion counts and derived rates from (label, prediction) pairs.

    ``label``/``prediction`` are booleans where ``True`` is the positive class
    (for contradiction detection: "a confirmed contradiction exists").
    """
    tp = fp = fn = tn = 0
    for label, predicted in pairs:
        if label and predicted:
            tp += 1
        elif label and not predicted:
            fn += 1
        elif not label and predicted:
            fp += 1
        else:
            tn += 1

    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = _rate(2 * tp, 2 * tp + fp + fn)
    false_positive_rate = _rate(fp, fp + tn)
    false_negative_rate = _rate(fn, fn + tp)
    accuracy = _rate(tp + tn, tp + fp + fn + tn)

    return {
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "support": tp + fp + fn + tn,
        "positives": tp + fn,
        "negatives": fp + tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
        "accuracy": accuracy,
    }


def compute_status_accuracy(expected: list[str], predicted: list[str]) -> dict:
    """Accuracy for a multi-class label (used for evidence-sufficiency statuses)."""
    total = len(expected)
    correct = sum(1 for e, p in zip(expected, predicted) if e == p)
    # Per-class confusion as a small table for transparency.
    labels = sorted(set(expected) | set(predicted))
    per_class = {}
    for label in labels:
        tp = sum(1 for e, p in zip(expected, predicted) if e == label and p == label)
        fp = sum(1 for e, p in zip(expected, predicted) if e != label and p == label)
        fn = sum(1 for e, p in zip(expected, predicted) if e == label and p != label)
        per_class[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": _rate(tp, tp + fp),
            "recall": _rate(tp, tp + fn),
        }
    return {
        "total": total,
        "correct": correct,
        "accuracy": _rate(correct, total),
        "per_class": per_class,
    }
