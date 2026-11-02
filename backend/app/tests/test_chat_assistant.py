"""Tests for the investigation chat assistant.

The assistant must (a) answer only from the investigation's own stored records,
(b) attach resolvable citations to every factual answer, (c) never leak another
investigation's records, and (d) say explicitly when the data cannot answer the
question instead of inventing an answer.
"""
from __future__ import annotations

import hashlib
import json

from app.demo import scenario
from app.models import Claim, Conclusion, Conflict, Document, DocumentContent, Evidence, Hypothesis, Investigation
from app.tests.conftest import run_investigation_sync


# --------------------------------------------------------------------- helpers
def _load_and_run_demo(db) -> int:
    _, investigation_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, investigation_id)
    db.expire_all()
    return investigation_id


def _seed_document(
    db,
    *,
    filename: str,
    text: str,
    subject: str,
    predicate: str,
    value: float,
    unit: str,
) -> tuple[Document, Claim]:
    document = Document(
        filename=filename,
        stored_filename=filename,
        file_type="txt",
        content_type="text/plain",
        file_size=len(text),
        checksum=hashlib.sha256(f"{filename}:{text}".encode()).hexdigest(),
        status="processed",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentContent(
            document_id=document.id,
            text=text,
            page_map='[{"page": null, "start": 0}]',
            char_count=len(text),
        )
    )
    claim = Claim(
        document_id=document.id,
        claim_text=text,
        subject=subject,
        predicate=predicate,
        object_value=f"{value:g} {unit}",
        numeric_value=value,
        unit=unit,
        polarity="affirmative",
        claim_type="measurement",
        source_reference=filename,
        source_location=filename,
        confidence=0.8,
    )
    db.add(claim)
    db.flush()
    return document, claim


def _ask(client, investigation_id: int, question: str, **hints) -> dict:
    response = client.post(
        f"/api/investigations/{investigation_id}/chat",
        json={"question": question, **hints},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_numbered(citations: list[dict]) -> None:
    assert citations, "a grounded answer must include at least one citation"
    assert [citation["number"] for citation in citations] == list(
        range(1, len(citations) + 1)
    )
    for citation in citations:
        assert citation["text_location"]
        assert citation["kind"]


def _assert_scope(db, investigation_id: int, body: dict) -> None:
    investigation = db.get(Investigation, investigation_id)
    document_ids = {document.id for document in investigation.documents}
    for citation in body["citations"]:
        if citation["document_id"] is not None:
            assert citation["document_id"] in document_ids
            assert citation["document_filename"]
            assert citation["link"] == f"/documents/{citation['document_id']}"


# ------------------------------------------------------------------ conflict
def test_demo_conflict_question_quotes_stored_detection_reason(db, client):
    investigation_id = _load_and_run_demo(db)
    conflict = db.query(Conflict).order_by(Conflict.id).first()
    assert conflict is not None

    body = _ask(
        client,
        investigation_id,
        "Why was this conflict detected?",
        conflict_id=conflict.id,
    )

    assert body["intent"] == "conflict_detected"
    assert body["insufficient_information"] is False
    assert str(conflict.id) in body["answer"]
    assert conflict.conflict_type in body["answer"]
    assert conflict.description[:40] in body["answer"]
    assert conflict.detection_method in body["answer"]
    assert body["follow_up_questions"]
    assert body["methodology"] and body["caveat"]

    _assert_numbered(body["citations"])
    _assert_scope(db, investigation_id, body)
    assert any(citation["document_filename"] for citation in body["citations"])

    # Every claim/evidence/conflict citation resolves to a real stored row.
    claim_ids = {row.id for row in db.query(Claim).all()}
    evidence_ids = {row.id for row in db.query(Evidence).all()}
    for citation in body["citations"]:
        if citation["kind"] == "claim":
            assert citation["record_id"] in claim_ids
        elif citation["kind"] == "evidence":
            assert citation["record_id"] in evidence_ids
        elif citation["kind"] == "conflict":
            assert citation["record_id"] == conflict.id


def test_conflict_question_does_not_use_another_investigation(db, client):
    investigation_id = _load_and_run_demo(db)
    unrelated = Conflict(
        claim_a_id=db.query(Claim).first().id,
        claim_b_id=db.query(Claim).first().id,
        conflict_type="semantic_inconsistency",
        description="Unrelated conflict from another investigation.",
        severity="low",
        confidence=0.2,
    )
    db.add(unrelated)
    db.commit()

    body = _ask(
        client,
        investigation_id,
        "Why was this conflict detected?",
        conflict_id=unrelated.id,
    )
    assert body["insufficient_information"] is True
    assert "not part of this investigation" in body["answer"]
    assert body["citations"] == []
    assert any("not linked to investigation" in item for item in body["missing_information"])


# ------------------------------------------------------------- claim support
def test_claim_support_reports_no_independent_support_and_contradiction(db, client):
    investigation_id = _load_and_run_demo(db)
    claim = db.query(Claim).filter(Claim.numeric_value == 92.0).first()
    assert claim is not None

    body = _ask(
        client,
        investigation_id,
        "Which document supports this claim?",
        claim_id=claim.id,
    )

    assert body["intent"] == "claim_support"
    assert body["insufficient_information"] is True
    assert claim.claim_text in body["answer"]
    assert "No independent stored document" in body["answer"]
    assert "Inspection_Report_B.txt" in body["answer"]
    assert body["missing_information"]

    _assert_numbered(body["citations"])
    _assert_scope(db, investigation_id, body)
    assert any(
        citation["kind"] == "claim" and citation["record_id"] == claim.id
        for citation in body["citations"]
    )
    assert any(
        citation["document_filename"] == "Inspection_Report_A.txt"
        for citation in body["citations"]
    )


def test_claim_support_names_the_corroborating_document(db, client):
    report_1, claim_1 = _seed_document(
        db,
        filename="report_1.txt",
        text="Pump P-9 flow was 120 L/min at 09:00.",
        subject="pump p-9",
        predicate="flow",
        value=120,
        unit="L/min",
    )
    report_2, _ = _seed_document(
        db,
        filename="report_2.txt",
        text="Pump P-9 flow was 120.5 L/min at 09:05.",
        subject="pump p-9",
        predicate="flow",
        value=120.5,
        unit="L/min",
    )
    investigation = Investigation(
        name="Pump flow corroboration",
        research_question="Which document supports the reported flow?",
        status="completed",
    )
    investigation.documents = [report_1, report_2]
    db.add(investigation)
    db.commit()

    body = _ask(
        client,
        investigation.id,
        "Which document supports this claim?",
        claim_id=claim_1.id,
    )

    assert body["intent"] == "claim_support"
    assert body["insufficient_information"] is False
    assert "Supported" in body["answer"]
    assert "report_2.txt" in body["answer"]
    _assert_numbered(body["citations"])
    _assert_scope(db, investigation.id, body)
    assert any(
        citation["document_filename"] == "report_2.txt"
        for citation in body["citations"]
    )


def test_claim_from_another_investigation_is_not_used(db, client):
    investigation_id = _load_and_run_demo(db)
    unrelated_doc, unrelated_claim = _seed_document(
        db,
        filename="unrelated.txt",
        text="Valve V-3 pressure was 12 bar.",
        subject="valve v-3",
        predicate="pressure",
        value=12,
        unit="bar",
    )
    db.commit()

    body = _ask(
        client,
        investigation_id,
        "Which document supports this claim?",
        claim_id=unrelated_claim.id,
    )
    assert body["insufficient_information"] is True
    assert "not part of this investigation" in body["answer"]
    assert body["citations"] == []
    cited_ids = {citation["document_id"] for citation in body["citations"]}
    assert unrelated_doc.id not in cited_ids


# --------------------------------------------------------------- hypotheses
def test_hypothesis_contradiction_lists_stored_evidence(db, client):
    investigation_id = _load_and_run_demo(db)
    hypothesis = (
        db.query(Hypothesis)
        .filter(Hypothesis.conflict_id.isnot(None))
        .order_by(Hypothesis.id)
        .first()
    )
    evidence = (
        db.query(Evidence)
        .filter(Evidence.document_id.isnot(None), Evidence.conflict_id == hypothesis.conflict_id)
        .order_by(Evidence.id)
        .first()
    )
    assert hypothesis is not None and evidence is not None
    evidence.supports_hypothesis_id = None
    evidence.contradicts_hypothesis_id = hypothesis.id
    hypothesis.contradicting_evidence_ids = json.dumps([evidence.id])
    db.commit()

    body = _ask(
        client,
        investigation_id,
        "What evidence contradicts this hypothesis?",
        hypothesis_id=hypothesis.id,
    )

    assert body["intent"] == "hypothesis_contradiction"
    assert body["insufficient_information"] is False
    assert hypothesis.title in body["answer"]
    assert f"Evidence #{evidence.id}" in body["answer"]
    assert evidence.description[:40] in body["answer"]
    _assert_numbered(body["citations"])
    _assert_scope(db, investigation_id, body)
    assert any(
        citation["kind"] == "evidence" and citation["record_id"] == evidence.id
        for citation in body["citations"]
    )
    assert any(citation["document_filename"] for citation in body["citations"])


# ------------------------------------------------------ inconclusive / gaps
def test_inconclusive_question_quotes_conclusion_and_unresolved_questions(db, client):
    investigation_id = _load_and_run_demo(db)
    conclusion = (
        db.query(Conclusion)
        .filter(Conclusion.investigation_id == investigation_id)
        .order_by(Conclusion.id.desc())
        .first()
    )
    assert conclusion is not None
    assert conclusion.decision_type in {
        "inconclusive",
        "human_review_required",
        "tentative_conclusion",
    }

    body = _ask(client, investigation_id, "Why is the investigation inconclusive?")

    assert body["intent"] == "investigation_inconclusive"
    assert body["insufficient_information"] is False
    assert conclusion.decision_type in body["answer"]
    assert conclusion.conclusion[:60] in body["answer"]
    assert "Calibration history" in body["answer"]
    _assert_numbered(body["citations"])
    _assert_scope(db, investigation_id, body)
    assert any(
        citation["kind"] == "conclusion" and citation["record_id"] == conclusion.id
        for citation in body["citations"]
    )
    assert any(citation["document_filename"] for citation in body["citations"])


def test_missing_evidence_question_lists_recorded_gaps(db, client):
    investigation_id = _load_and_run_demo(db)
    body = _ask(client, investigation_id, "What additional evidence is required?")

    assert body["intent"] == "missing_evidence"
    assert body["insufficient_information"] is False
    assert "Calibration history" in body["answer"]
    assert body["missing_information"]
    _assert_numbered(body["citations"])
    _assert_scope(db, investigation_id, body)
    assert any(
        citation["kind"] in {"hypothesis", "conclusion", "evidence"}
        for citation in body["citations"]
    )
    assert any(citation["document_filename"] for citation in body["citations"])


# ------------------------------------------------------------- unsupported
def test_unknown_question_is_explicitly_unanswerable(db, client):
    investigation_id = _load_and_run_demo(db)
    body = _ask(client, investigation_id, "What is the capital of France?")

    assert body["insufficient_information"] is True
    assert "cannot answer from the current investigation data" in body["answer"]
    assert body["citations"] == []
    assert body["missing_information"]
    assert body["follow_up_questions"]


def test_empty_investigation_is_honest(db, client):
    investigation = Investigation(
        name="Empty investigation",
        research_question="Nothing has been loaded yet.",
        status="created",
    )
    db.add(investigation)
    db.commit()

    body = _ask(client, investigation.id, "Summarise this investigation.")
    assert body["intent"] == "summary"
    assert body["insufficient_information"] is True
    assert "No source documents are attached" in body["answer"]
    assert body["data_sources"]["documents"] == 0
    _assert_numbered(body["citations"])

    missing = _ask(client, investigation.id, "What additional evidence is required?")
    assert missing["insufficient_information"] is True
    assert "do not list any missing information" in missing["answer"]


def test_suggestions_and_missing_investigation(client, db):
    investigation_id = _load_and_run_demo(db)
    suggestions = client.get(
        f"/api/investigations/{investigation_id}/chat/suggestions"
    )
    assert suggestions.status_code == 200
    body = suggestions.json()
    assert body["investigation_id"] == investigation_id
    assert body["suggestions"]
    assert any("conflict" in item.lower() for item in body["suggestions"])

    assert client.get("/api/investigations/999999/chat/suggestions").status_code == 404
    response = client.post(
        "/api/investigations/999999/chat",
        json={"question": "Summarise this investigation."},
    )
    assert response.status_code == 404
