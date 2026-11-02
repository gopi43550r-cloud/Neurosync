"""API endpoint tests using FastAPI TestClient."""
from __future__ import annotations

import time


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ai_configured"] is False
    assert body["mode"] == "demonstration"


def test_upload_txt(client):
    files = [("files", ("report.txt", b"The temperature was 65C at 09:00.", "text/plain"))]
    resp = client.post("/api/documents/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["status"] == "processed"
    assert data[0]["claim_count"] >= 1

    docs = client.get("/api/documents").json()
    assert docs["total"] == 1


def test_invalid_file_rejected(client):
    files = [("files", ("bad.exe", b"binary", "application/octet-stream"))]
    resp = client.post("/api/documents/upload", files=files)
    assert resp.status_code == 415


def test_empty_upload_rejected(client):
    files = [("files", ("empty.txt", b"", "text/plain"))]
    resp = client.post("/api/documents/upload", files=files)
    assert resp.status_code == 400


def _poll_investigation(client, investigation_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/investigations/{investigation_id}").json()
        if body["status"] in ("completed", "cancelled", "error"):
            return body
        time.sleep(0.3)
    return client.get(f"/api/investigations/{investigation_id}").json()


def test_demo_scenario_end_to_end(client):
    load = client.post("/api/demo/load").json()
    assert load["is_demo"] is True
    inv_id = load["investigation_id"]

    started = client.post(f"/api/investigations/{inv_id}/start").json()
    assert started["status"] in ("running", "created")

    final = _poll_investigation(client, inv_id)
    assert final["status"] == "completed"
    assert final["iteration_count"] >= 1

    conflicts = client.get("/api/conflicts").json()
    assert conflicts["total"] >= 1

    detail = client.get(f"/api/conflicts/{conflicts['items'][0]['id']}").json()
    assert detail["claim_a"] is not None
    assert detail["why_flagged"]

    hyps = client.get(f"/api/conflicts/{conflicts['items'][0]['id']}/hypotheses").json()
    assert len(hyps) >= 1

    report = client.get(f"/api/investigations/{inv_id}/report").json()
    assert report["sections"]
    assert report["stopping_reason"]

    md = client.get(f"/api/investigations/{inv_id}/report/export?format=markdown")
    assert md.status_code == 200
    assert "Investigation Report" in md.text

    activity = client.get(f"/api/investigations/{inv_id}/activity").json()
    assert len(activity) >= 1


def test_investigation_requires_scope(client):
    resp = client.post("/api/investigations", json={"name": "x"})
    assert resp.status_code == 422


def test_blackboard_snapshot(client):
    client.post("/api/demo/load")
    snapshot = client.get("/api/blackboard/snapshot").json()
    assert "counts" in snapshot
    assert "graph" in snapshot
    assert snapshot["counts"]["documents"] >= 3


def test_manual_hypothesis_and_evidence(client):
    load = client.post("/api/demo/load").json()
    inv_id = load["investigation_id"]
    client.post(f"/api/investigations/{inv_id}/start")
    _poll_investigation(client, inv_id)

    conflicts = client.get("/api/conflicts").json()
    cid = conflicts["items"][0]["id"]

    hyp = client.post(
        f"/api/conflicts/{cid}/hypotheses",
        json={"title": "A user-proposed explanation", "explanation": "Because reasons."},
    )
    assert hyp.status_code == 201
    hyp_id = hyp.json()["id"]

    ev = client.post(
        f"/api/conflicts/{cid}/evidence",
        json={"description": "User note about the calibration.", "supports_hypothesis_id": hyp_id},
    )
    assert ev.status_code == 201
    assert ev.json()["origin"] == "user"


def test_demo_reset(client):
    client.post("/api/demo/load")
    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200
    assert client.get("/api/documents").json()["total"] == 0
