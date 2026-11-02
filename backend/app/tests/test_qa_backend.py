"""QA backend behaviour tests (Tasks 1 and 4).

Exercises the HTTP API, the orchestration pipeline and database persistence
against an isolated temporary SQLite database (see ``conftest.py``). The suite
never touches real data and never needs an API key.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Claim, Conclusion, Conflict, Evidence, Hypothesis, Investigation
from app.schemas.investigation import InvestigationCreate
from app.services import document_service, investigation_service
from app.tests.conftest import run_investigation_sync

DOC_A = "Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM."
DOC_B = "Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM."


def _seed(db) -> dict:
    """Create two conflicting documents and run an investigation to completion.

    Returns plain ids (and commits) so the HTTP client can read/write the same
    database without contention from this session.
    """
    a = document_service.create_document_from_text(db, "A.txt", DOC_A, is_demo=True)
    document_service.process_document(db, a, extract=True)
    b = document_service.create_document_from_text(db, "B.txt", DOC_B, is_demo=True)
    document_service.process_document(db, b, extract=True)

    inv = investigation_service.create_investigation(
        db,
        InvestigationCreate(
            name="QA backend",
            research_question="",
            document_ids=[a.id, b.id],
            iteration_limit=25,
            min_evidence_threshold=1,
            enable_llm=False,
        ),
    )
    run_investigation_sync(db, inv.id)
    db.expire_all()
    conflict = db.query(Conflict).first()
    conclusion = (
        db.query(Conclusion).filter(Conclusion.conflict_id == conflict.id).first()
    )
    ids = {
        "investigation_id": inv.id,
        "document_a": a.id,
        "document_b": b.id,
        "conflict_id": conflict.id,
        "conclusion_id": conclusion.id,
    }
    db.commit()
    return ids


# ----------------------------------------------------------------- startup / shutdown
def test_startup_health_ok(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["effective_mode"] in ("deterministic", "ai_assisted")
    assert body["reasoning_mode"] in ("deterministic", "ai_assisted")


def test_app_starts_and_stops_repeatedly(db):
    for _ in range(3):
        with TestClient(app) as c:
            assert c.get("/api/health").status_code == 200


def test_config_reports_upload_limit(client):
    body = client.get("/api/config").json()
    assert body["max_upload_mb"] > 0
    assert "ai_configured" in body


# ----------------------------------------------------------------- API validation
def test_create_investigation_requires_scope(client):
    resp = client.post("/api/investigations", json={"name": "no scope"})
    assert resp.status_code == 422


def test_create_investigation_unknown_document_is_404(client):
    resp = client.post(
        "/api/investigations", json={"name": "x", "document_ids": [999999]}
    )
    assert resp.status_code == 404


def test_create_investigation_rejects_bad_iteration_limit(client):
    resp = client.post(
        "/api/investigations",
        json={"name": "x", "document_ids": [1], "iteration_limit": 0},
    )
    assert resp.status_code == 422


def test_invalid_reasoning_mode_rejected(client):
    assert client.put("/api/settings/reasoning", json={"mode": "bogus"}).status_code == 422


def test_reasoning_mode_roundtrip_degrades_without_provider(client):
    resp = client.put("/api/settings/reasoning", json={"mode": "ai_assisted"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reasoning_mode"] == "ai_assisted"
    # no provider configured in tests -> effective mode degrades, with an explanation
    assert body["effective_mode"] == "deterministic"
    assert body["note"]


def test_search_requires_a_query(client):
    assert client.get("/api/search").status_code == 422


# ----------------------------------------------------------------- upload / retrieval
def test_upload_and_retrieve_document(client):
    resp = client.post(
        "/api/documents/upload",
        files={"files": ("note.txt", DOC_A.encode(), "text/plain")},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    doc_id = results[0]["id"]
    assert results[0]["status"] == "processed"

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["filename"] == "note.txt"

    assert client.get("/api/documents").json()["total"] == 1


def test_upload_rejects_unsupported_type(client):
    resp = client.post(
        "/api/documents/upload",
        files={"files": ("bad.exe", b"data", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_upload_rejects_empty_file(client):
    resp = client.post(
        "/api/documents/upload", files={"files": ("empty.txt", b"", "text/plain")}
    )
    assert resp.status_code == 400


def test_upload_detects_duplicate(client):
    payload = DOC_A.encode()
    first = client.post(
        "/api/documents/upload", files={"files": ("dup.txt", payload, "text/plain")}
    ).json()
    second = client.post(
        "/api/documents/upload", files={"files": ("dup.txt", payload, "text/plain")}
    ).json()
    assert second[0]["duplicate"] is True
    assert second[0]["id"] == first[0]["id"]


def test_duplicate_upload_leaves_no_orphan_file(client):
    payload = DOC_A.encode()
    client.post("/api/documents/upload", files={"files": ("dup.txt", payload, "text/plain")})
    before = set(document_service.UPLOAD_DIR.iterdir())
    second = client.post(
        "/api/documents/upload", files={"files": ("dup.txt", payload, "text/plain")}
    ).json()
    assert second[0]["duplicate"] is True
    # The rejected duplicate must not leave a new file behind.
    assert set(document_service.UPLOAD_DIR.iterdir()) == before


def test_oversized_upload_rejected_and_leaves_no_file(client, monkeypatch):
    monkeypatch.setattr(document_service, "MAX_BYTES", 8)
    before = set(document_service.UPLOAD_DIR.iterdir())
    resp = client.post(
        "/api/documents/upload",
        files={"files": ("big.txt", b"far more than eight bytes here", "text/plain")},
    )
    assert resp.status_code == 413
    assert set(document_service.UPLOAD_DIR.iterdir()) == before



def test_reprocess_does_not_duplicate_claims(client):
    resp = client.post(
        "/api/documents/upload", files={"files": ("note.txt", DOC_A.encode(), "text/plain")}
    )
    doc_id = resp.json()[0]["id"]
    before = client.get(f"/api/documents/{doc_id}").json()["claim_count"]
    client.post(f"/api/documents/{doc_id}/reprocess")
    after = client.get(f"/api/documents/{doc_id}").json()["claim_count"]
    assert before == after


def test_delete_document(client):
    resp = client.post(
        "/api/documents/upload",
        files={"files": ("note.txt", b"M-17 temperature note.", "text/plain")},
    )
    doc_id = resp.json()[0]["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


# ----------------------------------------------------------------- pipeline (service level)
def test_pipeline_extracts_claims_conflicts_hypotheses_evidence_conclusion(db):
    _seed(db)
    assert db.query(Claim).count() >= 2

    conflict = db.query(Conflict).first()
    assert conflict is not None
    assert conflict.conflict_type == "numerical_disagreement"
    assert db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict.id).count() >= 1
    assert db.query(Evidence).filter(Evidence.conflict_id == conflict.id).count() >= 1
    assert db.query(Conclusion).filter(Conclusion.conflict_id == conflict.id).count() >= 1


def test_conclusion_confidence_is_bounded(db):
    _seed(db)
    for conclusion in db.query(Conclusion).all():
        assert 0.0 <= conclusion.confidence <= 1.0
    for conflict in db.query(Conflict).all():
        assert 0.0 <= conflict.confidence <= 1.0


def test_data_persists_across_sessions(db):
    ids = _seed(db)
    other = SessionLocal()
    try:
        assert other.get(Investigation, ids["investigation_id"]) is not None
        assert other.get(Conflict, ids["conflict_id"]) is not None
    finally:
        other.close()


# ----------------------------------------------------------------- investigation API
def test_investigation_completes_with_stop_reason(client, db):
    ids = _seed(db)
    body = client.get(f"/api/investigations/{ids['investigation_id']}").json()
    assert body["status"] == "completed"
    assert body["stop_reason"]
    assert body["conflict_count"] >= 1

    activity = client.get(f"/api/investigations/{ids['investigation_id']}/activity").json()
    assert isinstance(activity, list) and len(activity) >= 1


def test_investigation_report_and_export(client, db):
    ids = _seed(db)
    report = client.get(f"/api/investigations/{ids['investigation_id']}/report")
    assert report.status_code == 200
    assert report.json()["markdown"]

    md = client.get(
        f"/api/investigations/{ids['investigation_id']}/report/export", params={"format": "markdown"}
    )
    assert md.status_code == 200
    assert md.text

    pdf = client.get(
        f"/api/investigations/{ids['investigation_id']}/report/export", params={"format": "pdf"}
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    bad = client.get(
        f"/api/investigations/{ids['investigation_id']}/report/export", params={"format": "xml"}
    )
    assert bad.status_code == 422


# ----------------------------------------------------------------- conflict API
def test_conflict_detail_ranking_and_evidence_gaps(client, db):
    ids = _seed(db)
    cid = ids["conflict_id"]

    detail = client.get(f"/api/conflicts/{cid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["claim_a"] and body["claim_b"]
    assert body["why_flagged"]
    assert len(body["hypotheses"]) >= 1
    assert body["conclusion"] is not None

    ranking = client.get(f"/api/conflicts/{cid}/hypotheses/ranking")
    assert ranking.status_code == 200
    assert isinstance(ranking.json(), list)

    gaps = client.get(f"/api/conflicts/{cid}/evidence-gaps")
    assert gaps.status_code == 200
    assert isinstance(gaps.json(), list)


def test_conflict_patch_validates_status(client, db):
    ids = _seed(db)
    cid = ids["conflict_id"]
    assert client.patch(f"/api/conflicts/{cid}", json={"status": "not-a-status"}).status_code == 422
    ok = client.patch(f"/api/conflicts/{cid}", json={"status": "investigating"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "investigating"


# ----------------------------------------------------------------- human review workflow
def test_human_review_approval_resolves_conflict(client, db):
    ids = _seed(db)
    resp = client.post(
        f"/api/conclusions/{ids['conclusion_id']}/review",
        json={"decision": "approved", "reviewer": "QA", "note": "Looks right."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["review"]["decision"] == "approved"
    assert body["review"]["reviewer"] == "QA"
    assert body["conflict_status"] == "resolved"

    history = client.get(f"/api/conclusions/{ids['conclusion_id']}/reviews").json()
    assert len(history) == 1

    conflict = client.get(f"/api/conflicts/{ids['conflict_id']}").json()
    assert conflict["status"] == "resolved"


def test_human_review_rejection_reopens_conflict(client, db):
    ids = _seed(db)
    body = client.post(
        f"/api/conclusions/{ids['conclusion_id']}/review",
        json={"decision": "rejected", "reviewer": "QA"},
    ).json()
    assert body["conflict_status"] == "open"


def test_human_review_invalid_decision_rejected(client, db):
    ids = _seed(db)
    resp = client.post(
        f"/api/conclusions/{ids['conclusion_id']}/review", json={"decision": "maybe"}
    )
    assert resp.status_code == 422


def test_human_review_unknown_conclusion_rejected(client):
    resp = client.post("/api/conclusions/999999/review", json={"decision": "approved"})
    assert resp.status_code == 422


# ----------------------------------------------------------------- 404 handling
def test_unknown_entities_return_404(client):
    assert client.get("/api/investigations/999999").status_code == 404
    assert client.get("/api/documents/999999").status_code == 404
    assert client.get("/api/conflicts/999999").status_code == 404
    assert client.delete("/api/documents/999999").status_code == 404
    assert client.get("/api/conflicts/999999/hypotheses/ranking").status_code == 404
    assert client.get("/api/conflicts/999999/evidence-gaps").status_code == 404


# ----------------------------------------------------------------- search / demo
def test_search_finds_seeded_entities(client, db):
    _seed(db)
    body = client.get("/api/search", params={"q": "temperature"}).json()
    assert body["query"] == "temperature"
    for key in ("documents", "claims", "conflicts", "evidence", "hypotheses", "investigations"):
        assert key in body


def test_demo_scenario_loads_and_resets(client):
    loaded = client.post("/api/demo/load")
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["is_demo"] is True
    assert body["investigation_id"] is not None
    assert len(body["documents"]) >= 3
    assert client.get("/api/documents").json()["total"] >= 3

    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200
    assert client.get("/api/documents").json()["total"] == 0
