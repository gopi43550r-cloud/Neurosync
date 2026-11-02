"""CSV and PDF exports for evaluation runs.

Both renderers receive a fully-populated :class:`EvaluationRunOut` plus the
originating dataset, so the exported artifact contains exactly what the API
returned: dataset identity, provenance, per-case ground truth, the system's
prediction, pass/fail and the derived metrics. Nothing is re-computed here, so
an export can never disagree with the dashboard.

PDF rendering reuses PyMuPDF (already a dependency for document extraction) and
the same sanitising layout as the investigation report, so untrusted case text
cannot break the layout or inject markup. Regression rates with an undefined
denominator are printed as ``n/a`` rather than an invented number.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..schemas.evaluation import EvaluationRunOut
from .report_pdf import _Layout
from .report_service import safe_text  # noqa: F401  (re-exported for tests)

PROVENANCE_LABELS = {
    "reference_labelled": "Reference benchmark (curated, human-labelled)",
    "user_labelled": "User-labelled test set",
}

DISCLAIMER = (
    "Reference benchmarks are curated human-labelled fixtures, not independently "
    "audited field trials. A detected conflict is only counted correct when a "
    "ground-truth label says so; unlabelled demonstration records are never scored."
)


def _fmt(value: Any) -> str:
    """Render a metric value without inventing a number for an undefined rate."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _iso(value: Any) -> str:
    if value is None:
        return ""
    try:
        return value.isoformat()
    except AttributeError:  # already a string
        return str(value)


def _pdf_fmt(value: Any) -> str:
    """Compact, quote-free rendering for the PDF (the layout HTML-escapes)."""
    if isinstance(value, dict):
        return ", ".join(f"{key}={_pdf_fmt(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_pdf_fmt(item) for item in value)
    return _fmt(value)


def _overall(payload: EvaluationRunOut) -> dict:
    overall = (payload.metrics or {}).get("overall") or {}
    return overall if isinstance(overall, dict) else {}


def _metric_rows(payload: EvaluationRunOut) -> list[tuple[str, str]]:
    overall = _overall(payload)
    rows: list[tuple[str, str]] = []
    counts = overall.get("counts")
    if isinstance(counts, dict):
        for key in ("tp", "fp", "fn", "tn"):
            if key in counts:
                rows.append((key.upper(), _fmt(counts[key])))
        for key in (
            "support",
            "positives",
            "negatives",
            "precision",
            "recall",
            "f1",
            "accuracy",
            "false_positive_rate",
            "false_negative_rate",
        ):
            if key in overall:
                rows.append((key.replace("_", " ").title(), _fmt(overall[key])))
    elif overall.get("labels") is not None:
        for key in ("total", "correct", "accuracy", "macro_precision", "macro_recall", "macro_f1"):
            if key in overall:
                rows.append((key.replace("_", " ").title(), _fmt(overall[key])))
        per_class = overall.get("per_class") or {}
        for label, values in per_class.items():
            rows.append(
                (
                    f"class {label}",
                    (
                        f"support={values.get('support')} precision={_fmt(values.get('precision'))} "
                        f"recall={_fmt(values.get('recall'))} f1={_fmt(values.get('f1'))}"
                    ),
                )
            )
    else:
        rows.append(("Metrics", _fmt(overall)))

    signals = (payload.metrics or {}).get("signals") or {}
    for key, value in signals.items():
        rows.append((f"Signal: {key.replace('_', ' ')}", _fmt(value)))
    return rows


def _confusion_rows(payload: EvaluationRunOut) -> list[list[Any]]:
    confusion = payload.confusion or {}
    if payload.kind == "conflict_detection" and isinstance(confusion, dict):
        if all(key in confusion for key in ("tp", "fp", "fn", "tn")):
            return [["expected", "predicted", "count"], *[
                ["positive", "positive", confusion.get("tp", 0)],
                ["negative", "positive", confusion.get("fp", 0)],
                ["positive", "negative", confusion.get("fn", 0)],
                ["negative", "negative", confusion.get("tn", 0)],
            ]]
    rows: list[list[Any]] = [["expected", "predicted", "count"]]
    if isinstance(confusion, dict):
        for expected, predictions in confusion.items():
            if not isinstance(predictions, dict):
                continue
            for predicted, count in predictions.items():
                if count:
                    rows.append([expected, predicted, count])
    return rows


def _category_rows(payload: EvaluationRunOut) -> list[list[Any]]:
    rows: list[list[Any]] = [["category", "metrics"]]
    for category, values in sorted((payload.by_category or {}).items()):
        rows.append([category, _fmt(values)])
    return rows


def _result_rows(payload: EvaluationRunOut) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["case_key", "category", "expected", "predicted", "passed", "duration_ms", "explanation"]
    ]
    for result in payload.results:
        rows.append(
            [
                result.case_key,
                result.category,
                _fmt(result.expected),
                _fmt(result.predicted),
                "PASS" if result.passed else "FAIL",
                result.duration_ms,
                result.explanation,
            ]
        )
    return rows


def _header_rows(payload: EvaluationRunOut, dataset: Any) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["NeuroSync evaluation export"],
        ["Dataset", payload.dataset_name],
        ["Dataset key", getattr(dataset, "key", "")],
        ["Dataset version", getattr(dataset, "version", "")],
        ["Dataset source", getattr(dataset, "source", "")],
        ["Evaluation kind", payload.kind],
        ["Provenance", PROVENANCE_LABELS.get(payload.provenance, payload.provenance)],
        ["Run id", payload.id],
        ["Status", payload.status],
        ["Cases", payload.case_count],
        ["Passed", payload.passed],
        ["Failed", payload.failed],
        ["Duration (ms)", payload.duration_ms],
        ["Started", _iso(payload.started_at)],
        ["Completed", _iso(payload.completed_at)],
        ["Note", DISCLAIMER],
    ]
    if payload.error:
        rows.append(["Error", payload.error])
    return rows


# ------------------------------------------------------------------------- CSV
def render_csv(payload: EvaluationRunOut, dataset: Any = None) -> str:
    """Render a run as a sectioned CSV document (UTF-8, BOM added by caller)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in _header_rows(payload, dataset):
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["Metrics"])
    for name, value in _metric_rows(payload):
        writer.writerow([name, value])

    writer.writerow([])
    writer.writerow(["Confusion"])
    for row in _confusion_rows(payload):
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["Per-category metrics"])
    for row in _category_rows(payload):
        writer.writerow(row)

    if payload.failures:
        writer.writerow([])
        writer.writerow(["Failures"])
        writer.writerow(["case_key", "category", "failure_kind", "explanation"])
        for failure in payload.failures:
            writer.writerow(
                [
                    failure.get("case_key") or failure.get("id", ""),
                    failure.get("category", ""),
                    failure.get("failure_kind", ""),
                    failure.get("explanation", ""),
                ]
            )

    writer.writerow([])
    writer.writerow(["Test results"])
    for row in _result_rows(payload):
        writer.writerow(row)

    return buffer.getvalue()


# ------------------------------------------------------------------------- PDF
def _pdf_section(layout: "_Layout", heading: str) -> None:
    layout.space(6)
    layout.write(heading, size=12, bold=True)
    layout.space(1)


def render_pdf(payload: EvaluationRunOut, dataset: Any = None) -> bytes:
    """Render a run as a paginated A4 PDF."""
    layout = _Layout()
    layout.write("NeuroSync Evaluation Report", size=17, bold=True)
    layout.space(2)
    layout.write(f"Dataset: {payload.dataset_name}", size=10.5)
    layout.write(
        f"Kind: {payload.kind}    Provenance: "
        f"{PROVENANCE_LABELS.get(payload.provenance, payload.provenance)}",
        size=9.5,
    )
    layout.write(
        f"Run {payload.id}    Status: {payload.status}    "
        f"Cases: {payload.case_count}    Passed: {payload.passed}    Failed: {payload.failed}",
        size=9.5,
    )
    layout.write(
        f"Started: {_iso(payload.started_at)}    Completed: {_iso(payload.completed_at)}    "
        f"Duration: {payload.duration_ms} ms",
        size=9.5,
    )
    if payload.error:
        layout.write(f"Error: {payload.error}", size=9.5, bold=True)
    layout.space(3)
    layout.write(DISCLAIMER, size=9)
    layout.rule()

    _pdf_section(layout, "Summary metrics")
    for name, value in _metric_rows(payload):
        layout.write(f"{name}: {value}", size=10)

    _pdf_section(layout, "Confusion matrix")
    confusion = _confusion_rows(payload)
    if len(confusion) <= 1:
        layout.write("No confusion data was recorded for this run.", size=10)
    else:
        for row in confusion:
            layout.write(" | ".join(_pdf_fmt(cell) for cell in row), size=10)

    _pdf_section(layout, "Per-category metrics")
    for category, values in sorted((payload.by_category or {}).items()):
        layout.write(f"{category}: {_pdf_fmt(values)}", size=9.5)

    if payload.failures:
        _pdf_section(layout, "Failures")
        for failure in payload.failures:
            key = failure.get("case_key") or failure.get("id", "")
            layout.write(
                f"\u2022 {key} [{failure.get('failure_kind', 'mismatch')}]: "
                f"{failure.get('explanation', '')}",
                size=9.5,
                indent=8.0,
            )

    _pdf_section(layout, "Test results")
    for result in payload.results:
        verdict = "PASS" if result.passed else "FAIL"
        layout.write(
            f"[{verdict}] {result.case_key} ({result.category})", size=10, bold=True
        )
        layout.write(f"Expected: {_pdf_fmt(result.expected)}", size=9, indent=8.0)
        layout.write(f"Predicted: {_pdf_fmt(result.predicted)}", size=9, indent=8.0)
        if result.explanation:
            layout.write(f"Why: {result.explanation}", size=9, indent=8.0)
        layout.space(2)

    pdf_bytes = layout.doc.tobytes()
    layout.doc.close()
    return pdf_bytes
