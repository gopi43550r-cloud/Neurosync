"""Tests for claim-level fact verification.

The verifier must (a) use only stored claims/evidence/documents, (b) expose a
verdict from the four allowed labels, (c) show grounded citations with a source
document and page/character location, (d) mark insufficient claims Unverified,
and (e) never accept an AI-written citation that does not resolve to a record.
"""
from __future__ import annotations

import hashlib

from app.config import settings
from app.demo import scenario
from app.models import Claim, Document, DocumentContent, Evidence
from app.services import llm_service as llm_module
from app.services import settings_service
from app.services.fact_verification_service import build_index, verify_claim
from app.services.llm_service import LLMProvider
from app.tests.conftest import run_investigation_sync

VERDICTS = {"supported", "contradicted", "partially_supported", "unverified"}


# --------------------------------------------------------------------- helpers
def _seed_claim(
    db,
    *,
    filename: str,
    text: str,
    subject: str,
    predicate: str,
    claim_type: str = "measurement",
    numeric_value: float | None = None,
    unit: str = "",
    object_value: str = "",
    polarity: str = "affirmative",
) -> Claim:
    """Create a processed document with one explicitly controlled claim."""
    doc = Document(
        filename=filename,
        stored_filename=filename,
        file_type="txt",
        content_type="text/plain",
        file_size=len(text),
        checksum=hashlib.sha256(f"{filename}:{text}".encode()).hexdigest(),
        status="processed",
    )
    db.add(doc)
    db.flush()
    db.add(
        DocumentContent(
            document_id=doc.id,
            text=text,
            page_map='[{"page": null, "start": 0}]',
            char_count=len(text),
        )
    )
    claim = Claim(
        document_id=doc.id,
        claim_text=text,
        subject=subject,
        predicate=predicate,
        claim_type=claim_type,
        numeric_value=numeric_value,
        unit=unit,
        object_value=object_value,
        polarity=polarity,
        source_reference=filename,
        source_location=filename,
        confidence=0.7,
    )
    db.add(claim)
    db.flush()
    return claim


def _load_and_run_demo(db) -> int:
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)
    db.expire_all()
    return inv_id


def _all_citation_ids(items: list[dict]) -> set[tuple[str, int | None]]:
    return {
        (item["kind"], item["record_id"])
        for item in items
        if item.get("record_id") is not None
    }


# ----------------------------------------------------------------- integration
def test_demo_claims_get_grounded_verdicts_and_citations(db, client):
    inv_id = _load_and_run_demo(db)
    claims = db.query(Claim).order_by(Claim.id).all()
    claim_ids = {c.id for c in claims}
    evidence_ids = {e.id for e in db.query(Evidence).all()}
    document_ids = {d.id for d in db.query(Document).all()}
    assert len(claims) == 3

    resp = client.get("/api/verification/claims", params={"page_size": 100})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["counts"]["contradicted"] == 2
    assert body["counts"]["unverified"] == 1
    assert body["documents_considered"] == 3
    assert body["methodology"] and body["caveat"]

    for item in body["items"]:
        assert item["verdict"] in VERDICTS
        assert item["verdict_label"]
        assert item["explanation"]
        assert item["summary"]
        assert isinstance(item["missing_information"], list)
        assert item["source"]["document_id"] in document_ids
        assert item["source"]["document_filename"]

        for evidence_item in (
            item["supporting_evidence"]
            + item["contradicting_evidence"]
            + item["neutral_evidence"]
        ):
            # Every citation resolves to a real stored record.
            if evidence_item["kind"] == "claim":
                assert evidence_item["record_id"] in claim_ids
            elif evidence_item["kind"] == "evidence":
                assert evidence_item["record_id"] in evidence_ids
            elif evidence_item["kind"] == "document":
                assert evidence_item["record_id"] is None
                assert evidence_item["source"]["document_id"] in document_ids
            else:  # pragma: no cover - defensive
                raise AssertionError(f"unknown item kind {evidence_item['kind']}")
            assert evidence_item["source"]["text_location"]
            assert evidence_item["reason"]

    contradicted = [i for i in body["items"] if i["verdict"] == "contradicted"]
    for item in contradicted:
        assert item["contradicting_evidence"]
        assert item["supporting_evidence"] == []
        # The demo's contradiction is the 92 °C vs 76 °C disagreement.
        assert any(
            "92" in (e["source"].get("snippet") or "") or "76" in (e["source"].get("snippet") or "")
            for e in item["contradicting_evidence"]
        )

    unverified = [i for i in body["items"] if i["verdict"] == "unverified"]
    assert unverified[0]["supporting_evidence"] == []
    assert unverified[0]["contradicting_evidence"] == []
    assert unverified[0]["missing_information"]

    # Summary endpoint agrees with the list.
    summary = client.get("/api/verification/summary").json()
    assert summary["total_claims"] == 3
    assert summary["counts"]["contradicted"] == 2
    assert summary["claims_with_contradictions"] == 2

    # Investigation-scoped endpoint returns the same claims.
    scoped = client.get(
        f"/api/investigations/{inv_id}/claim-verifications", params={"page_size": 100}
    )
    assert scoped.status_code == 200
    scoped_body = scoped.json()
    assert scoped_body["total"] == 3
    assert scoped_body["investigation_id"] == inv_id
    assert scoped_body["investigation_name"]
    assert {i["claim_id"] for i in scoped_body["items"]} == claim_ids


def test_investigation_scope_excludes_unrelated_claims(db, client):
    inv_id = _load_and_run_demo(db)
    _seed_claim(
        db,
        filename="unrelated.txt",
        text="Valve V-3 pressure was 12 bar during the night shift.",
        subject="valve v-3",
        predicate="pressure",
        numeric_value=12,
        unit="bar",
    )
    db.commit()

    assert client.get("/api/verification/claims").json()["total"] == 4
    scoped = client.get(f"/api/investigations/{inv_id}/claim-verifications").json()
    assert scoped["total"] == 3


def test_claim_without_any_evidence_is_unverified(db, client):
    claim = _seed_claim(
        db,
        filename="lonely.txt",
        text="Compressor K-2 efficiency was 81% on its own inspection log.",
        subject="compressor k-2",
        predicate="efficiency",
        numeric_value=81,
        unit="%",
    )
    db.commit()

    resp = client.get(f"/api/claims/{claim.id}/verification")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "unverified"
    assert body["verdict_label"] == "Unverified"
    assert body["supporting_evidence"] == []
    assert body["contradicting_evidence"] == []
    assert body["source"]["document_filename"] == "lonely.txt"
    assert body["source"]["text_location"]
    assert any("No independent" in m for m in body["missing_information"])
    # Never invent a citation for an unsupported claim.
    assert all(e.get("record_id") is None for e in body["neutral_evidence"])


def test_supported_then_partially_supported_when_contradiction_appears(db, client):
    target = _seed_claim(
        db,
        filename="report_1.txt",
        text="Pump P-9 flow was 120 L/min at 09:00.",
        subject="pump p-9",
        predicate="flow",
        numeric_value=120,
        unit="L/min",
    )
    _seed_claim(
        db,
        filename="report_2.txt",
        text="Pump P-9 flow was 120.5 L/min at 09:05.",
        subject="pump p-9",
        predicate="flow",
        numeric_value=120.5,
        unit="L/min",
    )
    db.commit()

    first = client.get(f"/api/claims/{target.id}/verification").json()
    assert first["verdict"] == "supported"
    assert first["supporting_evidence"]
    assert first["contradicting_evidence"] == []

    _seed_claim(
        db,
        filename="report_3.txt",
        text="Pump P-9 flow was 90 L/min at 09:10.",
        subject="pump p-9",
        predicate="flow",
        numeric_value=90,
        unit="L/min",
    )
    db.commit()

    second = client.get(f"/api/claims/{target.id}/verification").json()
    assert second["verdict"] == "partially_supported"
    assert second["verdict_label"] == "Partially Supported"
    assert second["supporting_evidence"]
    assert second["contradicting_evidence"]
    assert any("reconciled" in m for m in second["missing_information"])


def test_unknown_verdict_filter_is_rejected(client):
    resp = client.get("/api/verification/claims", params={"verdict": "probably_true"})
    assert resp.status_code == 422


def test_missing_claim_and_investigation_return_404(client):
    assert client.get("/api/claims/999999/verification").status_code == 404
    assert client.get("/api/investigations/999999/claim-verifications").status_code == 404


# ------------------------------------------------------------------- AI layer
class _ExplanationProvider(LLMProvider):
    name = "fake"

    def __init__(self, explanation: str, citations: list[str]):
        self.payload = {"explanation": explanation, "cited_citations": citations}
        self.prompts: list[str] = []

    @property
    def available(self) -> bool:
        return True

    def chat(self, system, user, *, max_tokens, json_mode):
        self.prompts.append(user)
        import json

        return json.dumps(self.payload)


def _enable_ai(db, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-fake")
    monkeypatch.setattr(settings, "enable_llm", True)
    settings_service.set_reasoning_mode(db, settings_service.MODE_AI)


def _disable_ai(db):
    settings_service.set_reasoning_mode(db, settings_service.MODE_DETERMINISTIC)


def test_ai_explanation_with_fabricated_citation_is_rejected(db, client, monkeypatch):
    target = _seed_claim(
        db,
        filename="ai_target.txt",
        text="Boiler B-1 pressure was 8 bar at 06:00.",
        subject="boiler b-1",
        predicate="pressure",
        numeric_value=8,
        unit="bar",
    )
    _seed_claim(
        db,
        filename="ai_support.txt",
        text="Boiler B-1 pressure was 8.1 bar at 06:02.",
        subject="boiler b-1",
        predicate="pressure",
        numeric_value=8.1,
        unit="bar",
    )
    db.commit()

    provider = _ExplanationProvider("Fabricated AI summary.", ["claim:999999"])
    original = llm_module.llm_service.provider
    llm_module.llm_service.set_provider(provider)
    _enable_ai(db, monkeypatch)
    try:
        body = client.get(
            f"/api/claims/{target.id}/verification", params={"use_llm": "true"}
        ).json()
        assert body["verdict"] == "supported"
        assert body["method"] == "deterministic"
        assert "Fabricated AI summary" not in body["explanation"]
        assert any("rejected" in n for n in body["analysis_notes"])
    finally:
        llm_module.llm_service.set_provider(original)
        _disable_ai(db)


def test_ai_explanation_with_valid_citation_is_accepted(db, client, monkeypatch):
    target = _seed_claim(
        db,
        filename="ai_target_2.txt",
        text="Fan F-4 speed was 1450 rpm at 07:00.",
        subject="fan f-4",
        predicate="speed",
        numeric_value=1450,
        unit="rpm",
    )
    _seed_claim(
        db,
        filename="ai_support_2.txt",
        text="Fan F-4 speed was 1455 rpm at 07:01.",
        subject="fan f-4",
        predicate="speed",
        numeric_value=1455,
        unit="rpm",
    )
    db.commit()

    deterministic = verify_claim(db, db.get(Claim, target.id))
    assert deterministic["verdict"] == "supported"
    citation = next(
        f"{item['kind']}:{item['record_id']}"
        for item in deterministic["supporting_evidence"]
        if item.get("record_id") is not None
    )

    provider = _ExplanationProvider("Grounded AI rationale.", [citation])
    original = llm_module.llm_service.provider
    llm_module.llm_service.set_provider(provider)
    _enable_ai(db, monkeypatch)
    try:
        body = client.get(
            f"/api/claims/{target.id}/verification", params={"use_llm": "true"}
        ).json()
        assert body["method"] == "ai_assisted"
        assert "Grounded AI rationale" in body["explanation"]
        assert body["verdict"] == "supported"  # verdict is never changed by the LLM
        assert any("accepted" in n for n in body["analysis_notes"])
    finally:
        llm_module.llm_service.set_provider(original)
        _disable_ai(db)


def test_index_builds_once_and_reports_documents(db):
    _seed_claim(
        db,
        filename="index_a.txt",
        text="Motor M-8 current was 12 A.",
        subject="motor m-8",
        predicate="current",
        numeric_value=12,
        unit="A",
    )
    _seed_claim(
        db,
        filename="index_b.txt",
        text="Motor M-8 current was 12.1 A.",
        subject="motor m-8",
        predicate="current",
        numeric_value=12.1,
        unit="A",
    )
    db.commit()
    index = build_index(db)
    assert index.document_count == 2
    assert len(index.claims) == 2
