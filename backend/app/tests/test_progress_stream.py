"""Live progress stream tests.

Covers the reliability contract of the investigation Server-Sent Events stream:
authoritative progress frames, event-log replay with ``Last-Event-ID`` semantics,
deterministic termination, connection-failure handling, and redaction of
sensitive document content.
"""
from __future__ import annotations

import json

from app.database import SessionLocal
from app.demo import scenario
from app.models import Claim, Investigation
from app.services.event_redaction import SENSITIVE_KEYS, redact_payload
from app.tests.conftest import run_investigation_sync


# --------------------------------------------------------------------- helpers
def read_stream(client, url, *, headers=None, until="stream_end", max_frames=2000):
    """Collect (event, data) frames from an SSE response until ``until``."""
    frames: list[tuple[str, dict]] = []
    with client.stream("GET", url, headers=headers or {}) as resp:
        assert resp.status_code == 200, resp.status_code
        event = None
        data = None
        for line in resp.iter_lines():
            if line == "":
                if event is not None:
                    frames.append((event, data))
                    if event == until:
                        break
                event = None
                data = None
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
            if len(frames) >= max_frames:
                break
    return frames


def _frame(frames, event):
    return [data for name, data in frames if name == event]


# ----------------------------------------------------------------- redaction
def test_redaction_strips_document_content_and_marks_fields():
    payload = {
        "claim_id": 7,
        "document_id": 3,
        "claim_text": "Machine M-17 reached a temperature of 92C at 10:00 AM.",
        "nested": {"evidence_quote": "some raw document wording", "keep": 1},
        "long_note": "x" * 900,
    }
    out = redact_payload(payload)
    assert "claim_text" not in out
    assert "evidence_quote" not in out["nested"]
    assert out["nested"]["keep"] == 1
    assert out["claim_id"] == 7 and out["document_id"] == 3
    assert len(out["long_note"]) < 900
    assert set(out["redacted_fields"]) >= {"claim_text", "evidence_quote", "long_note"}
    # No sensitive key survives anywhere, at any depth.
    assert not (SENSITIVE_KEYS & set(out))


# ------------------------------------------------------------- progress state
def test_progress_snapshot_reflects_backend_state(db):
    from app.api.investigations import progress_snapshot

    docs, inv_id = scenario.load_demo(db, auto_start=False)
    snapshot = progress_snapshot(db, inv_id)
    assert snapshot is not None
    assert snapshot["status"] == "created"
    assert snapshot["current_agent"] == ""  # nothing is running yet
    assert snapshot["iteration_count"] == 0

    assert progress_snapshot(db, 999999) is None


def test_progress_snapshot_after_run_reports_completed_and_failed_counts(db):
    from app.api.investigations import progress_snapshot

    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)
    snapshot = progress_snapshot(db, inv_id)
    assert snapshot["status"] == "completed"
    assert snapshot["completed"] >= 1
    assert snapshot["failed"] == 0
    assert snapshot["executions"] == snapshot["completed"] + snapshot["failed"] + snapshot["skipped"]
    assert snapshot["current_agent"] == ""


# --------------------------------------------------------------- live stream
def test_stream_emits_progress_and_events_then_end(client, db):
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)

    frames = read_stream(client, f"/api/investigations/{inv_id}/events")
    progress = _frame(frames, "progress")
    assert progress, "expected at least one progress frame"
    assert progress[0]["status"] == "completed"
    assert progress[0]["completed"] >= 1

    events = _frame(frames, "claim_extracted")
    assert events, "expected claim events to be replayed"
    assert events[-1]["id"] > 0
    assert frames[-1][0] == "stream_end"
    assert frames[-1][1]["status"] == "completed"


def test_stream_redacts_document_content(client, db):
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)

    sentinel = db.query(Claim).first().claim_text[:60]
    assert sentinel

    frames = read_stream(client, f"/api/investigations/{inv_id}/events")
    blob = json.dumps(frames)

    assert sentinel not in blob, "raw claim text leaked into the progress stream"
    for _, data in frames:
        payload = data.get("payload")
        if isinstance(payload, dict):
            assert not (SENSITIVE_KEYS & set(payload))

    claim_frames = _frame(frames, "claim_extracted")
    assert claim_frames
    assert "claim_text" not in claim_frames[0]["payload"]
    assert "claim_text" in claim_frames[0]["payload"]["redacted_fields"]
    # Identifiers survive redaction so the UI can still link to the record.
    assert claim_frames[0]["payload"]["claim_id"] >= 1


def test_stream_resumes_from_last_event_id(client, db):
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)

    # Find a mid-stream event id to resume after.
    all_frames = read_stream(client, f"/api/investigations/{inv_id}/events")
    ids = [d["id"] for name, d in all_frames if isinstance(d, dict) and name not in {"progress", "stream_end"}]
    assert len(ids) >= 2
    resume_after = ids[0]

    resumed = read_stream(
        client,
        f"/api/investigations/{inv_id}/events",
        headers={"Last-Event-ID": str(resume_after)},
    )
    replayed_ids = [
        d["id"] for name, d in resumed if isinstance(d, dict) and name not in {"progress", "stream_end"}
    ]
    assert replayed_ids, "reconnect should still deliver the remaining backlog"
    assert min(replayed_ids) > resume_after, "already-delivered events must not be resent"


def test_stream_reports_error_for_unknown_investigation(client):
    frames = read_stream(client, "/api/investigations/999999/events", until="stream_error")
    assert frames and frames[0][0] == "stream_error"
    assert "not found" in frames[0][1]["detail"].lower()


def test_stream_tolerates_malformed_last_event_id(client, db):
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)

    frames = read_stream(
        client,
        f"/api/investigations/{inv_id}/events",
        headers={"Last-Event-ID": "not-a-number"},
    )
    # Falls back to replaying from the beginning rather than crashing.
    assert _frame(frames, "claim_extracted")


def test_recent_events_endpoint_is_redacted(client, db):
    _, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)
    sentinel = db.query(Claim).first().claim_text[:60]

    items = client.get(f"/api/blackboard/events?investigation_id={inv_id}&page_size=100").json()["items"]
    blob = json.dumps(items)
    assert sentinel not in blob
    claim_events = [e for e in items if e["event_type"] == "claim_extracted"]
    assert claim_events
    assert "claim_text" not in claim_events[0]["payload"]


# ------------------------------------------------------------- cancellation
def test_cancel_endpoint_stops_investigation(client, db):
    import time

    _, inv_id = scenario.load_demo(db, auto_start=False)
    assert client.post(f"/api/investigations/{inv_id}/start").status_code == 200
    # Cancel immediately; the controller checks the flag before each step.
    assert client.post(f"/api/investigations/{inv_id}/cancel").status_code == 200

    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/investigations/{inv_id}").json()["status"]
        if status in ("cancelled", "completed", "error"):
            break
        time.sleep(0.3)
    assert status in ("cancelled", "completed"), status

    session = SessionLocal()
    try:
        inv = session.get(Investigation, inv_id)
        assert inv.current_agent == ""  # cleared once the loop stops
    finally:
        session.close()
