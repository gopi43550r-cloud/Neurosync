"""Evidence-verification evaluation.

Each labelled case is materialised as real documents and claims, processed by
the production extraction path, and then verified with
``app.services.fact_verification_service.verify_claim``. The evaluator never
re-implements the verifier: it only supplies inputs and compares the engine's
verdict with the human-authored label.

Verdicts are the four production outcomes:
``supported``, ``contradicted``, ``partially_supported`` and ``unverified``.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Claim, Document, DocumentContent
from app.services import document_service
from app.services.fact_verification_service import build_scoped_index, verify_claim

from .metrics import compute_multiclass_metrics

VERDICT_LABELS = ["supported", "contradicted", "partially_supported", "unverified"]


class _DocumentFactory:
    """Persist a synthetic source document and extract its claims."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._n = 0

    def create(self, filename: str, text: str) -> Document:
        self._n += 1
        doc = Document(
            filename=filename or f"evidence_eval_doc_{self._n}.txt",
            stored_filename=f"evidence_eval_{self._n}.txt",
            file_type="txt",
            content_type="text/plain",
            file_size=len(text.encode("utf-8")),
            checksum=f"evidence-eval-{self._n}-{len(text)}",
            status="processed",
        )
        self.db.add(doc)
        self.db.flush()
        self.db.add(DocumentContent(document_id=doc.id, text=text, char_count=len(text)))
        self.db.flush()
        document_service.extract_document_content(self.db, doc)
        return doc

    def claims(self, document: Document) -> list[Claim]:
        return (
            self.db.query(Claim)
            .filter(Claim.document_id == document.id)
            .order_by(Claim.id)
            .all()
        )


def _citations(items: list[dict], limit: int = 4) -> list[dict]:
    out: list[dict] = []
    for item in items[:limit]:
        source = item.get("source") or {}
        out.append(
            {
                "relation": item.get("relation"),
                "document_filename": source.get("document_filename"),
                "text_location": source.get("text_location") or "source unknown",
                "snippet": (source.get("snippet") or item.get("text") or "")[:300],
                "reason": item.get("reason") or "",
                "independence": item.get("independence") or "",
            }
        )
    return out


def _no_claim_prediction() -> dict:
    return {
        "verdict": "unverified",
        "verdict_label": "Unverified",
        "confidence": 0.0,
        "summary": "No claim could be extracted from the target text, so no verdict was possible.",
        "explanation": (
            "The production claim extractor returned no machine-readable claim for the "
            "target text. The engine therefore reports Unverified rather than inventing "
            "a comparison."
        ),
        "supporting_count": 0,
        "contradicting_count": 0,
        "neutral_count": 0,
        "citations": [],
        "claim_extracted": False,
        "claim_text": "",
    }


def run_evidence_verification_evaluation(db: Session, dataset: dict) -> dict:
    factory = _DocumentFactory(db)
    results: list[dict] = []
    expected_labels: list[str] = []
    predicted_labels: list[str] = []
    per_category: dict[str, tuple[list[str], list[str]]] = {}

    for case in dataset["cases"]:
        claim_text = case.get("claim_text", "")
        target = factory.create("target_claim.txt", claim_text)
        docs = [target]
        for spec in case.get("documents", []):
            docs.append(factory.create(spec.get("filename", ""), spec.get("text", "")))

        target_claims = factory.claims(target)
        if target_claims:
            claim = target_claims[0]
            index = build_scoped_index(db, document_ids=[doc.id for doc in docs])
            verification = verify_claim(db, claim, index=index)
            predicted = {
                "verdict": verification["verdict"],
                "verdict_label": verification["verdict_label"],
                "confidence": verification["confidence"],
                "summary": verification["summary"],
                "explanation": verification["explanation"],
                "supporting_count": len(verification["supporting_evidence"]),
                "contradicting_count": len(verification["contradicting_evidence"]),
                "neutral_count": len(verification["neutral_evidence"]),
                "citations": _citations(
                    verification["supporting_evidence"] + verification["contradicting_evidence"]
                ),
                "claim_extracted": True,
                "claim_text": claim.claim_text,
                "subject": claim.subject,
                "predicate": claim.predicate,
                "numeric_value": claim.numeric_value,
                "unit": claim.unit,
                "missing_information": verification["missing_information"],
            }
        else:
            predicted = _no_claim_prediction()

        expected_verdict = case["expected"]["verdict"]
        passed = predicted["verdict"] == expected_verdict
        expected_labels.append(expected_verdict)
        predicted_labels.append(predicted["verdict"])
        per_category.setdefault(case.get("category", "general"), ([], []))
        per_category[case.get("category", "general")][0].append(expected_verdict)
        per_category[case.get("category", "general")][1].append(predicted["verdict"])

        results.append(
            {
                "id": case["id"],
                "category": case.get("category", "general"),
                "claim_text": claim_text,
                "documents": [
                    {"filename": spec.get("filename", ""), "role": spec.get("role", "context")}
                    for spec in case.get("documents", [])
                ],
                "expected_verdict": expected_verdict,
                "predicted_verdict": predicted["verdict"],
                "correct": passed,
                "prediction": predicted,
                "rationale": case.get("rationale", ""),
            }
        )

    overall = compute_multiclass_metrics(
        expected_labels, predicted_labels, labels=VERDICT_LABELS
    )
    by_category = {
        category: compute_multiclass_metrics(exp, pred, labels=VERDICT_LABELS)
        for category, (exp, pred) in sorted(per_category.items())
    }
    return {
        "dataset": {
            "name": dataset["name"],
            "version": dataset["version"],
            "num_cases": len(results),
            "labels": VERDICT_LABELS,
        },
        "overall": overall,
        "confusion": overall["confusion"],
        "by_category": by_category,
        "cases": results,
    }
