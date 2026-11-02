"""Evaluation-harness tests.

These run the curated evaluation datasets through the real extraction,
detection and scoring code and assert that (a) the harness executes, (b) the
metrics meet documented floors, and (c) known-hard examples remain the *only*
conflict-detection failures. They do not re-implement the pipeline.

The datasets are labelled evaluation fixtures kept under ``evaluation/datasets``
and are never loaded into a production database; the ``db`` fixture uses the
isolated test database like every other test in this suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import document_service
from evaluation import conflict_eval, evidence_eval

DATASETS_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "datasets"

# The only examples the detector is expected to get wrong; see evaluation/README.md.
EXPECTED_FAILURE_IDS = {
    "lex_subject_synonym_temp",
    "lex_state_synonym_running",
    "lex_negation_scope_false_positive",
}


def _load(name: str) -> dict:
    return json.loads((DATASETS_DIR / name).read_text(encoding="utf-8"))


def test_conflict_evaluation_runs(db):
    dataset = _load("conflicts.json")
    result = conflict_eval.run_conflict_evaluation(db, dataset)

    assert result["dataset"]["num_examples"] == len(dataset["examples"])
    assert result["overall"]["support"] == len(dataset["examples"])
    # Every category in the dataset is reported separately.
    for category in dataset["categories"]:
        assert category in result["by_category"]

    # Documented performance floors for the deterministic detector.
    assert result["overall"]["precision"] >= 0.85
    assert result["overall"]["recall"] >= 0.80
    assert result["overall"]["f1"] >= 0.80

    failure_ids = {f["id"] for f in result["failures"]}
    assert failure_ids == EXPECTED_FAILURE_IDS


def test_conflict_per_category_metrics_present(db):
    dataset = _load("conflicts.json")
    result = conflict_eval.run_conflict_evaluation(db, dataset)
    for category, metrics in result["by_category"].items():
        assert metrics["support"] > 0
        assert "precision" in metrics and "recall" in metrics
        assert "false_positive_rate" in metrics and "false_negative_rate" in metrics


def test_evidence_sufficiency_meets_contract(db):
    dataset = _load("evidence_sufficiency.json")
    result = evidence_eval.run_evidence_evaluation(db, dataset)

    assert result["dataset"]["num_scenarios"] == len(dataset["scenarios"])
    # The transparent scoring must honour every documented status contract.
    assert result["accuracy"]["accuracy"] == 1.0
    # Each hypothesis's supporting/contradicting evidence must be partitioned correctly.
    assert result["partition_traceability_rate"] == 1.0


def test_conclusion_traceability(db, tmp_path, monkeypatch):
    # Redirect demo document writes away from the production uploads directory.
    monkeypatch.setattr(document_service, "UPLOAD_DIR", tmp_path)

    result = evidence_eval.run_traceability_evaluation(db)

    assert result["conclusions_total"] >= 1
    assert result["traceability_rate"] == 1.0
    assert result["conclusions_linked_to_conflict"] == result["conclusions_total"]
    assert result["conclusions_linked_to_claims"] == result["conclusions_total"]
    for conclusion in result["conclusions"]:
        assert conclusion["support_ids_exist"]
        assert conclusion["support_ids_belong_to_conflict"]
        assert conclusion["support_sufficient"]
