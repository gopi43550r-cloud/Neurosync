"""Command-line entry point for the NeuroSync evaluation harness.

Usage (from ``neurosync/backend``)::

    python -m evaluation.run_evaluation

Runs the curated conflict-detection and evidence-sufficiency datasets plus the
conclusion-traceability audit through the *actual* application code, then writes
reproducible JSON and Markdown reports to ``evaluation/results/``.

Isolation guarantees:
    * ``DATABASE_URL`` is pointed at a throwaway SQLite file in a temporary
      directory, so no production database is touched.
    * The document-upload directory is redirected to a temporary directory, so
      the demonstration run writes no files into the production ``uploads/``.
    * ``ENABLE_LLM`` is forced off so results are deterministic and require no
      API key.

Reproducibility: metrics are a pure function of the datasets and the code; the
``generated_at`` timestamp is metadata only and does not affect any metric.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EVALUATION_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EVALUATION_DIR / "datasets"
DEFAULT_OUT_DIR = EVALUATION_DIR / "results"


def _bootstrap_isolated_environment() -> str:
    """Point the app at an isolated temp DB/uploads and force deterministic mode.

    Must run before any ``app.*`` module is imported.
    """
    tmp_root = tempfile.mkdtemp(prefix="neurosync_eval_")
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp_root, 'eval.db').as_posix()}"
    os.environ["ENABLE_LLM"] = "false"
    os.environ["OPENAI_API_KEY"] = ""
    return tmp_root


def _load_dataset(filename: str) -> dict:
    path = DATASETS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the NeuroSync evaluation harness.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for result files.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary database/uploads.")
    args = parser.parse_args(argv)

    tmp_root = _bootstrap_isolated_environment()

    # Imports happen after the environment is isolated.
    from app.database import Base, SessionLocal, engine  # noqa: E402
    from app import models  # noqa: F401,E402
    from app.services import document_service  # noqa: E402

    # Redirect demo document writes to the temp dir (keeps production uploads clean).
    document_service.UPLOAD_DIR = Path(tmp_root, "uploads")
    document_service.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    from . import conflict_eval, evidence_eval  # noqa: E402

    Base.metadata.create_all(bind=engine)

    conflict_dataset = _load_dataset("conflicts.json")
    evidence_dataset = _load_dataset("evidence_sufficiency.json")

    db = SessionLocal()
    try:
        conflict_results = conflict_eval.run_conflict_evaluation(db, conflict_dataset)
        evidence_results = evidence_eval.run_evidence_evaluation(db, evidence_dataset)
        traceability_results = evidence_eval.run_traceability_evaluation(db)
    finally:
        db.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": generated_at,
        "deterministic_mode": True,
        "llm_enabled": False,
        "dataset_hashes": {
            "conflicts.json": _sha256(DATASETS_DIR / "conflicts.json"),
            "evidence_sufficiency.json": _sha256(DATASETS_DIR / "evidence_sufficiency.json"),
        },
        "conflict_detection": conflict_results,
        "evidence_sufficiency": evidence_results,
        "conclusion_traceability": traceability_results,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "conflict_detection.json").write_text(
        json.dumps(conflict_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "evidence_sufficiency.json").write_text(
        json.dumps(evidence_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "conclusion_traceability.json").write_text(
        json.dumps(traceability_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(_render_summary(report), encoding="utf-8")

    _print_console_summary(report, out_dir)

    if not args.keep_temp:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return 0


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _render_summary(report: dict) -> str:
    cd = report["conflict_detection"]
    ov = cd["overall"]
    lines: list[str] = []
    lines.append("# NeuroSync Evaluation Summary")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- Deterministic mode: {report['deterministic_mode']} (LLM disabled)")
    lines.append("")
    lines.append("## Conflict detection (headline: confirmed contradictions)")
    lines.append("")
    lines.append(f"Positive class: {cd['dataset']['positive_class']} "
                 f"(types: {', '.join(cd['dataset']['confirmed_contradiction_types'])})")
    lines.append("")
    lines.append(f"- Examples: {cd['dataset']['num_examples']}")
    lines.append(f"- Precision: {_fmt(ov['precision'])}")
    lines.append(f"- Recall: {_fmt(ov['recall'])}")
    lines.append(f"- F1: {_fmt(ov['f1'])}")
    lines.append(f"- False-positive rate: {_fmt(ov['false_positive_rate'])}")
    lines.append(f"- False-negative rate: {_fmt(ov['false_negative_rate'])}")
    lines.append(f"- Accuracy: {_fmt(ov['accuracy'])}")
    lines.append(f"- Confusion: TP={ov['counts']['tp']}, FP={ov['counts']['fp']}, "
                 f"FN={ov['counts']['fn']}, TN={ov['counts']['tn']}")
    lines.append(f"- Flag accuracy (any conflict surfaced): {_fmt(cd['signals']['flag_accuracy'])}")
    lines.append(f"- Type accuracy: {_fmt(cd['signals']['type_accuracy'])}")
    lines.append("")
    lines.append("### Per category")
    lines.append("")
    lines.append("| Category | n | Precision | Recall | F1 | FPR | FNR |")
    lines.append("|---|---|---|---|---|---|---|")
    for category, m in cd["by_category"].items():
        lines.append(
            f"| {category} | {m['support']} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | "
            f"{_fmt(m['f1'])} | {_fmt(m['false_positive_rate'])} | {_fmt(m['false_negative_rate'])} |"
        )
    lines.append("")
    lines.append("### Failure cases")
    lines.append("")
    if cd["failures"]:
        for f in cd["failures"]:
            lines.append(f"- **{f['id']}** ({f['category']}, {f['failure_kind']}): {f['explanation']}")
    else:
        lines.append("- None: every example was classified correctly.")
    lines.append("")

    ev = report["evidence_sufficiency"]
    lines.append("## Evidence sufficiency")
    lines.append("")
    lines.append(f"- Scenarios: {ev['dataset']['num_scenarios']}")
    lines.append(f"- Status accuracy: {_fmt(ev['accuracy']['accuracy'])} "
                 f"({ev['accuracy']['correct']}/{ev['accuracy']['total']})")
    lines.append(f"- Evidence-partition traceability: {_fmt(ev['partition_traceability_rate'])}")
    lines.append("")
    lines.append("| Scenario | Expected | Predicted | Correct |")
    lines.append("|---|---|---|---|")
    for s in ev["scenarios"]:
        lines.append(
            f"| {s['id']} | {s['expected_status']} | {s['predicted_status']} | {s['correct']} |"
        )
    lines.append("")

    tr = report["conclusion_traceability"]
    lines.append("## Conclusion traceability (demo investigation)")
    lines.append("")
    lines.append(f"- Conclusions: {tr['conclusions_total']}")
    lines.append(f"- Fully traceable: {tr['fully_traceable']} "
                 f"(rate {_fmt(tr['traceability_rate'])})")
    lines.append(f"- Linked to conflict: {tr['conclusions_linked_to_conflict']}")
    lines.append(f"- Linked to source claims: {tr['conclusions_linked_to_claims']}")
    lines.append(f"- Decisions observed: {', '.join(tr['decisions']) or 'none'}")
    lines.append("")
    return "\n".join(lines)


def _print_console_summary(report: dict, out_dir: Path) -> None:
    cd = report["conflict_detection"]
    ov = cd["overall"]
    ev = report["evidence_sufficiency"]
    tr = report["conclusion_traceability"]
    print("NeuroSync evaluation complete")
    print("-" * 40)
    print(f"Conflict detection: precision={_fmt(ov['precision'])} recall={_fmt(ov['recall'])} "
          f"f1={_fmt(ov['f1'])} FPR={_fmt(ov['false_positive_rate'])} "
          f"FNR={_fmt(ov['false_negative_rate'])}")
    print(f"  examples={cd['dataset']['num_examples']} "
          f"TP={ov['counts']['tp']} FP={ov['counts']['fp']} "
          f"FN={ov['counts']['fn']} TN={ov['counts']['tn']}")
    print(f"  flag_accuracy={_fmt(cd['signals']['flag_accuracy'])} "
          f"type_accuracy={_fmt(cd['signals']['type_accuracy'])}")
    print(f"Evidence sufficiency: status_accuracy={_fmt(ev['accuracy']['accuracy'])} "
          f"partition_traceability={_fmt(ev['partition_traceability_rate'])}")
    print(f"Conclusion traceability: rate={_fmt(tr['traceability_rate'])} "
          f"({tr['fully_traceable']}/{tr['conclusions_total']})")
    if cd["failures"]:
        print(f"Failure cases: {len(cd['failures'])}")
        for f in cd["failures"]:
            print(f"  - {f['id']} [{f['failure_kind']}]")
    else:
        print("Failure cases: none")
    print(f"Results written to: {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
