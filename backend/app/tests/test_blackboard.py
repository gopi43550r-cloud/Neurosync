"""Blackboard service tests."""
from __future__ import annotations

from app.models import Conflict, Document, enums


def _doc(db, name="a.txt"):
    d = Document(filename=name, stored_filename=name, file_type="txt", status="processed", checksum=name)
    db.add(d)
    db.flush()
    return d


def test_add_observation_and_claim(blackboard, db):
    doc = _doc(db)
    obs = blackboard.add_observation(document_id=doc.id, text="Temperature was 65C.", observation_type="statement")
    claim = blackboard.add_claim(
        document_id=doc.id,
        observation_id=obs.id,
        claim_text="Temperature was 65C.",
        subject="temperature",
        predicate="measured_value",
        object_value="65C",
        numeric_value=65.0,
        unit="°C",
        claim_type="measurement",
    )
    blackboard.commit()
    assert obs.id is not None
    assert claim.id is not None
    assert blackboard.claims()[0].numeric_value == 65.0


def test_add_conflict_and_evidence(blackboard, db):
    doc_a = _doc(db, "a.txt")
    doc_b = _doc(db, "b.txt")
    ca = blackboard.add_claim(document_id=doc_a.id, claim_text="65C", subject="temperature", numeric_value=65.0, unit="°C", claim_type="measurement")
    cb = blackboard.add_claim(document_id=doc_b.id, claim_text="88C", subject="temperature", numeric_value=88.0, unit="°C", claim_type="measurement")
    con = blackboard.add_conflict(
        claim_a_id=ca.id, claim_b_id=cb.id, conflict_type="numerical_disagreement",
        description="diff", severity="high", confidence=0.7, status="open",
    )
    blackboard.add_evidence(conflict_id=con.id, description="calibration", evidence_type="calibration_record")
    blackboard.commit()
    assert len(blackboard.conflicts()) == 1
    assert len(blackboard.evidence(con.id)) == 1


def test_counts_and_snapshot(blackboard, db):
    doc = _doc(db)
    blackboard.add_claim(document_id=doc.id, claim_text="x", subject="temperature", claim_type="measurement")
    blackboard.commit()
    counts = blackboard.counts()
    assert counts["documents"] == 1
    assert counts["claims"] == 1
    snap = blackboard.snapshot()
    assert "counts" in snap and "graph" in snap
    assert any(n["node_type"] == "document" for n in snap["graph"]["nodes"])


def test_snapshot_persists_after_commit(db):
    from app.blackboard.blackboard_service import Blackboard

    doc = _doc(db)
    bb = Blackboard(db)
    bb.add_claim(document_id=doc.id, claim_text="persist", subject="temperature", claim_type="measurement")
    bb.commit()
    db.close()
    # New session should still see the data (persistence).
    session = __import__("app.database", fromlist=["SessionLocal"]).SessionLocal()
    try:
        bb2 = Blackboard(session)
        assert len(bb2.claims()) == 1
    finally:
        session.close()
