"""Report completeness, source traceability and export tests.

These tests exercise the upgraded reporting/explainability layer against the
shipped demonstration scenario. They assert that a report is *complete* (covers
every required section), *traceable* (every citation is backed by a real stored
record with a link) and *safe* (untrusted content is escaped, no storage paths
or secrets are emitted).
"""
from __future__ import annotations

from app.demo import scenario
from app.models import Claim, Conclusion, Conflict, Document, Evidence, Hypothesis, Investigation
from app.schemas.investigation import InvestigationCreate
from app.services import document_service, investigation_service
from app.services.report_service import build_report, escape_text, safe_text

REQUIRED_HEADINGS = {
    "Investigation Title and Identifier",
    "Objective",
    "Documents Analyzed",
    "Claims Extracted",
    "Conflicting Claims",
    "Evidence Supporting Each Relevant Claim",
    "Evidence Contradicting Each Relevant Claim",
    "Competing Hypotheses",
    "Verification Results",
    "Final Conclusion or Inconclusive Status",
    "Confidence and its Limitations",
    "Unresolved Questions",
    "Human Review Status",
    "Agent Activity Summary",
    "Limitations and Timestamps",
    "Audit Trail",
}

REQUIRED_JSON_KEYS = {
    "schema_version",
    "investigation",
    "documents",
    "claims",
    "conflicts",
    "evidence",
    "evidence_by_claim",
    "hypotheses",
    "verification",
    "conclusions",
    "confidence",
    "human_reviews",
    "human_review_status",
    "agent_activity",
    "audit_trail",
    "evidence_gaps",
    "unresolved_questions",
    "limitations",
    "timestamps",
    "warnings",
}


def _demo_full(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    from app.blackboard.controller import InvestigationControl, InvestigationController

    InvestigationController(db).run(inv_id, InvestigationControl())
    db.expire_all()
    return docs, inv_id


# --------------------------------------------------------------- completeness
def test_report_covers_all_required_items(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))

    headings = {s["heading"] for s in report["sections"]}
    missing = REQUIRED_HEADINGS - headings
    assert not missing, f"report is missing required sections: {missing}"

    data = report["json_data"]
    assert REQUIRED_JSON_KEYS <= set(data.keys())
    assert data["schema_version"] == report["schema_version"]

    # The report must reflect the actual records, not placeholder zeros.
    assert data["investigation"]["id"] == inv_id
    assert len(data["documents"]) == 3
    assert len(data["claims"]) >= 3
    assert len(data["conflicts"]) == 1
    assert data["conclusions"], "a conclusion record is expected for the demo conflict"
    assert data["audit_trail"], "the audit trail must not be empty"
    assert data["agent_activity"]["count"] >= 1


def test_report_marks_inconclusive_and_warns(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    data = report["json_data"]
    # The demonstration conflict is escalated to human review -> inconclusive.
    assert data["conclusions"][0]["is_inconclusive"] is True
    assert data["human_review_status"]["required"] is True
    assert any("human review" in w.lower() for w in data["warnings"])


# --------------------------------------------------------------- traceability
def test_every_citation_is_backed_by_a_real_record(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    data = report["json_data"]

    doc_ids = {d.id for d in db.query(Document).all()}
    claim_ids = {c.id for c in db.query(Claim).all()}
    evidence_ids = {e.id for e in db.query(Evidence).all()}
    conflict_ids = {c.id for c in db.query(Conflict).all()}

    # Documents
    for d in data["documents"]:
        assert d["id"] in doc_ids
        assert d["link"] == f"/documents/{d['id']}"

    # Claims must point at a real document.
    for c in data["claims"]:
        assert c["id"] in claim_ids
        assert c["document_id"] in doc_ids
        assert c["document_link"] == f"/documents/{c['document_id']}"

    # Conflicts reference real claims.
    for c in data["conflicts"]:
        assert c["id"] in conflict_ids
        assert c["link"] == f"/conflicts/{c['id']}"
        for ref in (c.get("claim_a"), c.get("claim_b")):
            if ref:
                assert ref["id"] in claim_ids
                assert ref["document_id"] in doc_ids

    # Evidence ids are real; links resolve to the evidence's document.
    for e in data["evidence"]:
        assert e["id"] in evidence_ids
        if e["document_id"] is not None:
            assert e["document_id"] in doc_ids
            assert e["document_link"] == f"/documents/{e['document_id']}"

    # Hypotheses reference real conflicts, and every cited evidence exists.
    for h in data["hypotheses"]:
        assert h["conflict_id"] in conflict_ids
        for ref in h["supporting_evidence"] + h["contradicting_evidence"]:
            if ref["exists"]:
                assert ref["id"] in evidence_ids

    # Per-claim evidence must map to real claims and evidence only.
    for entry in data["evidence_by_claim"]:
        assert entry["claim_id"] in claim_ids
        assert entry["conflict_id"] in conflict_ids
        for ev in entry["supporting_evidence"] + entry["contradicting_evidence"]:
            assert ev["id"] in evidence_ids

    # Verification rows are one-to-one with evidence.
    assert {v["evidence_id"] for v in data["verification"]} <= evidence_ids


def test_conclusion_supporting_evidence_is_real(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    conclusion_ids = {c.id for c in db.query(Conclusion).all()}
    evidence_ids = {e.id for e in db.query(Evidence).all()}
    for c in report["json_data"]["conclusions"]:
        assert c["id"] in conclusion_ids
        for ref in c["supporting_evidence"]:
            if ref["exists"]:
                assert ref["id"] in evidence_ids


def test_observed_facts_distinguished_from_inferred(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    data = report["json_data"]

    assert all(c["kind"] == "observed" for c in data["claims"])
    assert all(c["kind"] == "observed" for c in data["conflicts"])
    assert all(d["kind"] == "observed" for d in data["documents"])
    # Hypotheses are explanations, never presented as facts.
    assert data["hypotheses"] and all(h["kind"] == "inferred" for h in data["hypotheses"])
    # Evidence origin is reflected as observed vs inferred.
    for e in data["evidence"]:
        assert e["kind"] in ("observed", "inferred")


def test_audit_trail_entries_are_real(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    from app.models import AuditEvent

    real = {a.id for a in db.query(AuditEvent).filter(AuditEvent.investigation_id == inv_id).all()}
    trail_ids = {a["id"] for a in report["json_data"]["audit_trail"]}
    assert trail_ids
    assert trail_ids <= real


# ------------------------------------------------------------------- escaping
def test_escape_and_safe_text_helpers():
    assert safe_text("a\x00b\x07c") == "abc"
    assert safe_text("line\r\nbreak") == "line\nbreak"
    assert escape_text("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )
    assert escape_text("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def _investigation_with_malicious_claim(db):
    doc = document_service.create_document_from_text(
        db,
        filename="hostile.txt",
        text="<script>alert('pwned')</script> The value was 42.",
        is_demo=False,
    )
    document_service.process_document(db, doc, extract=False)
    claim = Claim(
        document_id=doc.id,
        claim_text="<script>alert('pwned')</script> The value was 42.",
        claim_type="statement",
        confidence=0.6,
    )
    db.add(claim)
    db.flush()
    inv = investigation_service.create_investigation(
        db,
        InvestigationCreate(
            name="Hostile input <b>test</b>",
            research_question="Does escaping work?",
            document_ids=[doc.id],
            enable_llm=False,
        ),
    )
    db.commit()
    return inv, claim


def test_report_escapes_untrusted_content_in_markdown_and_pdf(db):
    inv, claim = _investigation_with_malicious_claim(db)
    db.expire_all()
    report = build_report(db, db.get(Investigation, inv.id))

    # Raw markup must not survive verbatim into the markdown artifact.
    assert "<script>" not in report["markdown"]
    assert "&lt;script&gt;" in report["markdown"]
    assert "&lt;b&gt;" in report["markdown"]

    # JSON keeps the record readable (the client escapes on render).
    assert any("<script>" in c["claim_text"] for c in report["json_data"]["claims"])

    from app.services import report_pdf

    pdf = report_pdf.render_report_pdf(report)
    assert pdf.startswith(b"%PDF")
    # Text inside the PDF must not contain a literal script tag.
    text = b"".join(
        page.get_text().encode("latin-1", "replace") for page in __import__("fitz").open(stream=pdf)
    )
    assert b"<script>" not in text


def test_report_omits_storage_paths_and_secrets(db):
    _, inv_id = _demo_full(db)
    report = build_report(db, db.get(Investigation, inv_id))
    blob = report["markdown"] + str(report["json_data"])

    stored = [d.stored_filename for d in db.query(Document).all() if d.stored_filename]
    assert stored, "demo documents should have a stored filename"
    for name in stored:
        assert name not in blob, "internal storage filename leaked into the report"
    # Checksums are also internal metadata and must not be emitted.
    for d in db.query(Document).all():
        if d.checksum:
            assert d.checksum not in blob


# ---------------------------------------------------------------------- export
def test_api_report_and_exports(client, db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    inv = db.get(Investigation, inv_id)
    investigation_service.start_investigation(db, inv)
    import time

    deadline = time.time() + 30
    detail = client.get(f"/api/investigations/{inv_id}").json()
    while time.time() < deadline and detail["status"] not in ("completed", "cancelled", "error"):
        time.sleep(0.3)
        detail = client.get(f"/api/investigations/{inv_id}").json()

    report = client.get(f"/api/investigations/{inv_id}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["schema_version"] == 2
    assert body["sections"]
    assert body["json_data"]["investigation"]["id"] == inv_id

    md = client.get(f"/api/investigations/{inv_id}/report/export", params={"format": "markdown"})
    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    assert "text/html" not in md.headers["content-type"]

    js = client.get(f"/api/investigations/{inv_id}/report/export", params={"format": "json"})
    assert js.status_code == 200
    assert js.json()["investigation"]["id"] == inv_id

    pdf = client.get(f"/api/investigations/{inv_id}/report/export", params={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 1000
