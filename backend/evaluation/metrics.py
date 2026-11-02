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


def compute_multiclass_metrics(
    expected: list[str], predicted: list[str], labels: list[str] | None = None
) -> dict:
    """Full multi-class report with a confusion matrix.

    The caller supplies the label order so an absent class is still visible in
    the matrix (and its precision/recall is reported as ``None``, never zero).
    Macro averages skip undefined per-class rates so a label with no examples
    cannot silently deflate the headline score.
    """
    label_order = list(labels or sorted(set(expected) | set(predicted)))
    total = len(expected)
    correct = sum(1 for e, p in zip(expected, predicted) if e == p)

    per_class: dict[str, dict] = {}
    confusion: dict[str, dict[str, int]] = {
        label: {other: 0 for other in label_order} for label in label_order
    }
    for label, prediction in zip(expected, predicted):
        if label not in confusion:
            confusion[label] = {other: 0 for other in label_order}
        if prediction in confusion[label]:
            confusion[label][prediction] += 1

    for label in label_order:
        tp = sum(1 for e, p in zip(expected, predicted) if e == label and p == label)
        fp = sum(1 for e, p in zip(expected, predicted) if e != label and p == label)
        fn = sum(1 for e, p in zip(expected, predicted) if e == label and p != label)
        support = sum(1 for e in expected if e == label)
        precision = _rate(tp, tp + fp)
        recall = _rate(tp, tp + fn)
        per_class[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": _rate(2 * precision * recall, precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else (0.0 if precision == 0.0 or recall == 0.0 else None),
        }

    def _macro(field: str) -> float | None:
        values = [m[field] for m in per_class.values() if m[field] is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    return {
        "labels": label_order,
        "total": total,
        "correct": correct,
        "accuracy": _rate(correct, total),
        "macro_precision": _macro("precision"),
        "macro_recall": _macro("recall"),
        "macro_f1": _macro("f1"),
        "per_class": per_class,
        "confusion": confusion,
    }

