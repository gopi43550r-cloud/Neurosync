"""Conflict-detection evaluation.

Runs a curated, labeled dataset of claim-pair examples through the *actual*
NeuroSync code paths used in production:

    Document text
      -> app.services.document_service.extract_document_content  (rule-based extraction)
      -> app.services.conflict_service.detect_conflicts           (rule-based detection)

The evaluator never re-implements detection logic; it only arranges inputs and
compares the detector's output against human-authored labels. All rows are
written to an isolated database supplied by the caller (see ``run_evaluation``).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Claim, Document, DocumentContent
from app.services import document_service
from app.services.conflict_service import detect_conflicts

from .metrics import compute_binary_metrics

# Conflict types that represent a *confirmed* contradiction (the positive class).
CONFIRMED_CONTRADICTION_TYPES = {
    "numerical_disagreement",
    "direct_contradiction",
    "semantic_inconsistency",
}


class _DocumentFactory:
    """Creates synthetic source documents and persists their extracted claims.

    Uses the same extraction entry point as the Evidence Collector agent so the
    evaluation exercises real extraction behaviour, but stores no files and
    writes only to the caller's (temporary) database session.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._n = 0

    def claims_for(self, text: str) -> list[Claim]:
        self._n += 1
        name = f"eval_doc_{self._n}.txt"
        doc = Document(
            filename=name,
            stored_filename=name,
            file_type="txt",
            content_type="text/plain",
            file_size=len(text.encode("utf-8")),
            checksum=f"eval-{self._n}-{len(text)}",
            status="processed",
        )
        self.db.add(doc)
        self.db.flush()
        self.db.add(
            DocumentContent(document_id=doc.id, text=text, char_count=len(text))
        )
        self.db.flush()
        document_service.extract_document_content(self.db, doc)
        return (
            self.db.query(Claim).filter(Claim.document_id == doc.id).order_by(Claim.id).all()
        )


def _predict(claims_a: list[Claim], claims_b: list[Claim]) -> dict:
    conflicts = detect_conflicts(list(claims_a) + list(claims_b))
    types = sorted({c.conflict_type for c in conflicts})
    confirmed = sorted(t for t in types if t in CONFIRMED_CONTRADICTION_TYPES)
    return {
        "predicted_flag": len(conflicts) > 0,
        "predicted_types": types,
        "predicted_confirmed": len(confirmed) > 0,
        "confirmed_types": confirmed,
        "conflict_descriptions": [
            {
                "type": c.conflict_type,
                "severity": c.severity,
                "confidence": c.confidence,
                "description": c.description,
                "detection_method": c.detection_method,
            }
            for c in conflicts
        ],
    }


def run_conflict_evaluation(db: Session, dataset: dict) -> dict:
    factory = _DocumentFactory(db)

    examples: list[dict] = []
    metric_pairs: list[tuple[bool, bool]] = []
    per_category: dict[str, list[tuple[bool, bool]]] = {}
    flag_results: list[bool] = []
    type_results: list[bool] = []
    failures: list[dict] = []

    for ex in dataset["examples"]:
        claims_a = factory.claims_for(ex.get("text_a", ""))
        claims_b = factory.claims_for(ex.get("text_b", ""))
        prediction = _predict(claims_a, claims_b)

        label = bool(ex["label"])
        predicted = prediction["predicted_confirmed"]
        metric_pairs.append((label, predicted))
        per_category.setdefault(ex["category"], []).append((label, predicted))

        expected_flagged = bool(ex.get("expected_flagged", False))
        expected_types = list(ex.get("expected_types", []))
        if expected_types:
            type_correct = bool(set(expected_types) & set(prediction["predicted_types"]))
        else:
            type_correct = len(prediction["predicted_types"]) == 0
        flagged_correct = prediction["predicted_flag"] == expected_flagged
        flag_results.append(flagged_correct)
        type_results.append(type_correct)

        extraction_ok = bool(claims_a) and bool(claims_b)

        record = {
            "id": ex["id"],
            "category": ex["category"],
            "text_a": ex.get("text_a", ""),
            "text_b": ex.get("text_b", ""),
            "label": label,
            "predicted_confirmed": predicted,
            "classification_correct": label == predicted,
            "expected_flagged": expected_flagged,
            "expected_types": expected_types,
            "flagged_correct": flagged_correct,
            "type_correct": type_correct,
            "extraction": {
                "claims_a": len(claims_a),
                "claims_b": len(claims_b),
                "extraction_ok": extraction_ok,
            },
            "prediction": prediction,
            "rationale": ex.get("rationale", ""),
        }
        examples.append(record)

        if label != predicted:
            failures.append(
                {
                    "id": ex["id"],
                    "category": ex["category"],
                    "failure_kind": "false_positive" if predicted else "false_negative",
                    "explanation": _explain_failure(record, prediction, label),
                }
            )
        elif not flagged_correct:
            failures.append(
                {
                    "id": ex["id"],
                    "category": ex["category"],
                    "failure_kind": "flag_mismatch",
                    "explanation": (
                        f"Expected flagged={expected_flagged} but the detector "
                        f"returned flagged={prediction['predicted_flag']} "
                        f"(types={prediction['predicted_types']})."
                    ),
                }
            )
        elif not type_correct:
            failures.append(
                {
                    "id": ex["id"],
                    "category": ex["category"],
                    "failure_kind": "type_mismatch",
                    "explanation": (
                        f"Expected one of {expected_types} but the detector returned "
                        f"{prediction['predicted_types']}."
                    ),
                }
            )

    n = len(examples)
    return {
        "dataset": {
            "name": dataset["name"],
            "version": dataset["version"],
            "positive_class": dataset.get("positive_class", "confirmed_contradiction"),
            "confirmed_contradiction_types": sorted(CONFIRMED_CONTRADICTION_TYPES),
            "num_examples": n,
        },
        "overall": compute_binary_metrics(metric_pairs),
        "by_category": {
            category: compute_binary_metrics(pairs)
            for category, pairs in sorted(per_category.items())
        },
        "signals": {
            "flag_accuracy": round(sum(flag_results) / n, 4) if n else None,
            "type_accuracy": round(sum(type_results) / n, 4) if n else None,
            "extraction_coverage": round(
                sum(1 for e in examples if e["extraction"]["extraction_ok"]) / n, 4
            )
            if n
            else None,
        },
        "failures": failures,
        "examples": examples,
    }


def _explain_failure(record: dict, prediction: dict, label: bool) -> str:
    got = prediction["predicted_types"] or ["no conflict"]
    expected = record.get("expected_types") or ["no conflict (expected)"]
    if label and not prediction["predicted_confirmed"]:
        kind = "false negative: a real contradiction was missed"
    else:
        kind = "false positive: a non-contradiction was reported as a contradiction"
    ex = record.get("extraction", {})
    return (
        f"{kind}. Expected contradiction types {expected}, detector returned {got}. "
        f"Extraction produced claims_a={ex.get('claims_a')}, claims_b={ex.get('claims_b')}."
    )
