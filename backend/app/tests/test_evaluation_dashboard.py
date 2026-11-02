"""Tests for the AI Evaluation and Performance Dashboard.

These tests exercise the full evaluation pipeline against the real production
code paths: built-in dataset seeding, creating and uploading user-labelled
datasets, running conflict-detection and evidence-verification datasets in an
isolated session, computing metrics from persisted per-case results, dashboard
aggregation, CSV/PDF exports, and validation/error handling.

No metric is hard-coded without being traceable to the persisted outcomes; a
detected conflict is only correct when a ground-truth label says so.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models import Document, EvaluationRun
from app.schemas.evaluation import EvaluationDatasetIn
from app.services import evaluation_service
from app.services.evaluation_service import EvaluationValidationError


def _conflict_dataset_payload() -> dict:
    return {
        "name": "Temp conflict set",
        "kind": "conflict_detection",
        "description": "Two short texts",
        "version": "1.0.0",
        "cases": [
            {
                "case_key": "unit_conflict",
                "category": "units",
                "text_a": "The temperature was 100°F at 10:00 AM.",
                "text_b": "The temperature was 40°C at 10:00 AM.",
                "expected": {
                    "label": True,
                    "expected_flagged": True,
                    "expected_types": ["numerical_disagreement"],
                },
                "rationale": "Different temperatures after conversion.",
            },
            {
                "case_key": "unit_equiv",
                "category": "units",
                "text_a": "The temperature was 100°F at 10:00 AM.",
                "text_b": "The temperature was 37.8°C at 10:00 AM.",
                "expected": {
                    "label": False,
                    "expected_flagged": False,
                    "expected_types": [],
                },
                "rationale": "Equivalent readings.",
            },
        ],
    }


def _evidence_dataset_payload() -> dict:
    return {
        "name": "Evidence verdict set",
        "kind": "evidence_verification",
        "description": "Claim verification",
        "version": "1.0.0",
        "cases": [
            {
                "case_key": "agree",
                "category": "support",
                "claim_text": "The temperature was 92°C at 10:00 AM.",
                "documents": [
                    {
                        "filename": "b.txt",
                        "text": "The temperature was 92°C at 10:00 AM.",
                        "role": "supporting",
                    }
                ],
                "expected": {"verdict": "supported"},
                "rationale": "Same reading.",
            },
            {
                "case_key": "disagree",
                "category": "contradiction",
                "claim_text": "The machine was operating normally.",
                "documents": [
                    {
                        "filename": "note.txt",
                        "text": "The machine was not operating normally.",
                        "role": "contradicting",
                    }
                ],
                "expected": {"verdict": "contradicted"},
                "rationale": "Negation.",
            },
            {
                "case_key": "no_match",
                "category": "insufficient",
                "claim_text": "The temperature was 92°C at 10:00 AM.",
                "documents": [
                    {
                        "filename": "other.txt",
                        "text": "Maintenance is scheduled for Tuesday.",
                        "role": "context",
                    }
                ],
                "expected": {"verdict": "unverified"},
                "rationale": "Irrelevant.",
            },
        ],
    }


class TestEvaluationSeeding:
    def test_builtins_seed_idempotently(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        keys = {d.key for d in datasets}
        assert "builtin:conflict-detection" in keys
        assert "builtin:evidence-verification" in keys
        conflict = next(d for d in datasets if d.key == "builtin:conflict-detection")
        evidence = next(d for d in datasets if d.key == "builtin:evidence-verification")
        assert conflict.case_count == 32
        assert evidence.case_count == 9
        assert conflict.is_builtin is True
        assert conflict.source == "reference"


class TestEvaluationDatasets:
    def test_create_dataset_and_detail(self, db):
        payload = EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        dataset = evaluation_service.create_dataset(db, payload)
        assert dataset.key.startswith("user:")
        assert dataset.is_builtin is False
        assert dataset.source == "user"
        detail = evaluation_service.dataset_detail(db, dataset.id)
        assert len(detail.cases) == 2
        assert detail.cases[0].payload
        assert detail.cases[0].expected

    def test_upload_json_dataset(self, db):
        raw = json.dumps(_evidence_dataset_payload()).encode("utf-8")
        dataset = evaluation_service.create_dataset_from_json(db, raw)
        assert dataset.kind == "evidence_verification"
        detail = evaluation_service.dataset_detail(db, dataset.id)
        assert len(detail.cases) == 3

    def test_rejects_invalid_ground_truth(self, db):
        from pydantic import ValidationError

        bad = _conflict_dataset_payload()
        bad["cases"][0]["expected"] = {"label": "yes"}
        with pytest.raises(EvaluationValidationError):
            evaluation_service.create_dataset(
                db, EvaluationDatasetIn.model_validate(bad)
            )

        missing_verdict = _evidence_dataset_payload()
        missing_verdict["cases"][0]["expected"] = {}
        with pytest.raises(ValidationError):
            EvaluationDatasetIn.model_validate(missing_verdict)

    def test_rejects_non_json_upload(self, db):
        with pytest.raises(EvaluationValidationError):
            evaluation_service.create_dataset_from_json(db, b"not json")

    def test_cannot_delete_builtin(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        builtin = next(d for d in datasets if d.is_builtin)
        with pytest.raises(EvaluationValidationError):
            evaluation_service.delete_dataset(db, builtin.id)

    def test_delete_user_dataset_cascades(self, db):
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        assert run.status == "completed"
        assert evaluation_service.delete_dataset(db, dataset.id) is True
        assert evaluation_service.get_dataset(db, dataset.id) is None
        assert evaluation_service.get_run(db, run.id) is None


class TestEvaluationRuns:
    def test_run_conflict_dataset_with_real_pipeline(self, db):
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        assert run.status == "completed"
        assert run.case_count == 2
        assert run.passed == 2
        assert run.failed == 0
        out = evaluation_service.run_out(run)
        overall = out.metrics.get("overall", {})
        assert overall.get("counts") == {"fp": 0, "fn": 0, "tn": 1, "tp": 1}
        assert len(out.results) == 2
        for result in out.results:
            assert result.passed is True
            assert result.expected
            assert result.predicted

    def test_run_evidence_verification_dataset(self, db):
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_evidence_dataset_payload())
        )
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        out = evaluation_service.run_out(run)
        assert run.status == "completed"
        assert out.metrics["overall"]["accuracy"] == 1.0
        assert out.metrics["overall"]["labels"] == [
            "supported",
            "contradicted",
            "partially_supported",
            "unverified",
        ]
        assert out.confusion["supported"]["supported"] == 1
        assert out.confusion["contradicted"]["contradicted"] == 1
        assert out.confusion["unverified"]["unverified"] == 1

    def test_runs_never_pollute_real_documents(self, db):
        before = db.query(Document).count()
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        evaluation_service.execute_dataset_by_id(db, dataset.id)
        assert db.query(Document).count() == before

    def test_builtin_conflict_benchmark_matches_documented_floor(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        dataset = next(d for d in datasets if d.key == "builtin:conflict-detection")
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        out = evaluation_service.run_out(run)
        overall = out.metrics["overall"]
        assert overall["counts"] == {"tp": 10, "fp": 1, "fn": 2, "tn": 19}
        assert round(overall["precision"], 4) == 0.9091
        assert round(overall["recall"], 4) == 0.8333
        assert round(overall["f1"], 4) == 0.8696
        assert overall["accuracy"] == 0.9062
        failure_ids = {f.get("case_key") or f.get("id") for f in out.failures}
        assert {
            "lex_subject_synonym_temp",
            "lex_state_synonym_running",
            "lex_negation_scope_false_positive",
        }.issubset(failure_ids)

    def test_builtin_evidence_verification_benchmark(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        dataset = next(d for d in datasets if d.key == "builtin:evidence-verification")
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        out = evaluation_service.run_out(run)
        assert out.metrics["overall"]["accuracy"] == 1.0
        assert out.metrics["overall"]["macro_f1"] == 1.0
        assert out.passed == 9
        assert out.failed == 0

    def test_metrics_are_recomputed_not_stored_by_hand(self, db):
        """A persisted run's headline metrics follow its per-case results."""
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        out = evaluation_service.run_out(run)
        expected_tp = sum(
            1
            for result in out.results
            if result.expected.get("label") is True
            and result.predicted.get("predicted_confirmed") is True
        )
        expected_tn = sum(
            1
            for result in out.results
            if result.expected.get("label") is False
            and result.predicted.get("predicted_confirmed") is False
        )
        assert out.metrics["overall"]["counts"]["tp"] == expected_tp
        assert out.metrics["overall"]["counts"]["tn"] == expected_tn


class TestEvaluationAnalyticsAndExport:
    def test_dashboard_aggregates_real_data(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        for dataset in datasets:
            evaluation_service.execute_dataset_by_id(db, dataset.id)
        dash = evaluation_service.dashboard(db)
        assert dash.conflict_detection is not None
        assert dash.evidence_verification is not None
        assert dash.agents is not None
        assert dash.documents is not None
        assert dash.disclaimer
        assert dash.validation_note
        assert len(dash.datasets) >= 2
        assert any(d.is_builtin for d in dash.datasets)
        assert len(dash.agents.agents) == 6

    def test_dashboard_reports_live_document_and_agent_statistics(self, db):
        now = datetime.now(timezone.utc)
        db.add(
            Document(
                filename="live.txt",
                stored_filename="live.txt",
                file_type="txt",
                content_type="text/plain",
                file_size=10,
                checksum="live-checksum",
                status="processed",
                uploaded_at=now,
                processed_at=now,
            )
        )
        db.commit()
        dash = evaluation_service.dashboard(db)
        assert dash.documents.documents_total == 1
        assert dash.documents.documents_processed == 1

    def test_export_csv_and_pdf(self, db):
        evaluation_service.ensure_builtin_datasets(db)
        datasets = evaluation_service.list_datasets(db)
        dataset = next(d for d in datasets if d.key == "builtin:conflict-detection")
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        csv_bytes, csv_mt, csv_name = evaluation_service.export_run(db, run.id, "csv")
        assert csv_mt == "text/csv"
        assert csv_name.endswith(".csv")
        csv_text = csv_bytes.decode("utf-8-sig")
        assert "NeuroSync evaluation export" in csv_text
        assert "Metrics" in csv_text
        assert "Test results" in csv_text
        assert "lex_subject_synonym_temp" in csv_text
        pdf_bytes, pdf_mt, pdf_name = evaluation_service.export_run(db, run.id, "pdf")
        assert pdf_mt == "application/pdf"
        assert pdf_name.endswith(".pdf")
        assert pdf_bytes[:4] == b"%PDF"

    def test_export_rejects_unknown_format(self, db):
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        run = evaluation_service.execute_dataset_by_id(db, dataset.id)
        with pytest.raises(EvaluationValidationError):
            evaluation_service.export_run(db, run.id, "xlsx")


class TestEvaluationAPI:
    def test_api_flow(self, client):
        resp = client.get("/api/evaluation/datasets")
        assert resp.status_code == 200
        data = resp.json()
        keys = {d["key"] for d in data}
        assert "builtin:conflict-detection" in keys
        assert "builtin:evidence-verification" in keys

        conflict = next(d for d in data if d["key"] == "builtin:conflict-detection")
        resp = client.post(f"/api/evaluation/datasets/{conflict['id']}/run")
        assert resp.status_code == 201
        run = resp.json()
        assert run["status"] == "completed"
        assert run["provenance"] == "reference_labelled"
        assert run["passed"] + run["failed"] == run["case_count"]

        resp = client.get(f"/api/evaluation/runs/{run['id']}")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == run["case_count"]

        resp = client.get(f"/api/evaluation/runs/{run['id']}/export?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

        resp = client.get(f"/api/evaluation/runs/{run['id']}/export?format=pdf")
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers["content-type"]

        resp = client.get("/api/evaluation/dashboard")
        assert resp.status_code == 200
        dash = resp.json()
        assert dash["conflict_detection"] is not None
        assert dash["evidence_verification"] is None or dash["evidence_verification"]["kind"] == "evidence_verification"
        assert dash["documents"] is not None
        assert dash["agents"] is not None

        payload = _conflict_dataset_payload()
        resp = client.post("/api/evaluation/datasets", json=payload)
        assert resp.status_code == 201
        created = resp.json()
        assert created["case_count"] == 2
        assert created["source"] == "user"

        resp = client.post(
            "/api/evaluation/datasets/upload",
            files={
                "file": (
                    "set.json",
                    json.dumps(_evidence_dataset_payload()),
                    "application/json",
                )
            },
        )
        assert resp.status_code == 201
        uploaded = resp.json()
        assert uploaded["kind"] == "evidence_verification"
        assert uploaded["case_count"] == 3

        bad = _conflict_dataset_payload()
        bad["cases"][0]["expected"]["label"] = "x"
        resp = client.post("/api/evaluation/datasets", json=bad)
        assert resp.status_code == 422

        resp = client.post("/api/evaluation/datasets/not-a-number/run")
        assert resp.status_code == 422

        resp = client.get("/api/evaluation/runs/999999")
        assert resp.status_code == 404

    def test_cannot_export_failed_run(self, client, db):
        dataset = evaluation_service.create_dataset(
            db, EvaluationDatasetIn.model_validate(_conflict_dataset_payload())
        )
        run = EvaluationRun(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            kind=dataset.kind,
            provenance="user_labelled",
            status="failed",
            case_count=2,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        resp = client.get(f"/api/evaluation/runs/{run.id}/export?format=csv")
        assert resp.status_code == 409
