"""Conflict detection tests."""
from __future__ import annotations

from datetime import datetime

from app.models import Claim, Document
from app.services.conflict_service import compare_claims, conflict_exists, detect_conflicts


def _doc(db, name):
    d = Document(filename=name, stored_filename=name, file_type="txt", status="processed", checksum=name)
    db.add(d)
    db.flush()
    return d


def _claim(db, doc, **kw):
    defaults = dict(
        document_id=doc.id,
        claim_text=kw.get("claim_text", "x"),
        subject=kw.get("subject", "temperature"),
        predicate=kw.get("predicate", "measured_value"),
        claim_type=kw.get("claim_type", "measurement"),
        numeric_value=kw.get("numeric_value"),
        unit=kw.get("unit", "°C"),
        polarity=kw.get("polarity", "affirmative"),
        object_value=kw.get("object_value", ""),
        timestamp_value=kw.get("timestamp_value"),
    )
    c = Claim(**defaults)
    db.add(c)
    db.flush()
    return c


def test_identical_claims_no_conflict(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C")
    b = _claim(db, _doc(db, "b.txt"), numeric_value=65.0, unit="°C")
    assert compare_claims(a, b) is None


def test_numerical_disagreement(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C")
    b = _claim(db, _doc(db, "b.txt"), numeric_value=88.0, unit="°C")
    result = compare_claims(a, b)
    assert result is not None
    assert result.conflict_type == "numerical_disagreement"
    assert result.severity in ("medium", "high")


def test_different_times_classified_as_temporal_not_contradiction(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C", timestamp_value=datetime(2000, 1, 1, 9, 0))
    b = _claim(db, _doc(db, "b.txt"), numeric_value=88.0, unit="°C", timestamp_value=datetime(2000, 1, 1, 11, 30))
    result = compare_claims(a, b)
    assert result is not None
    assert result.conflict_type == "temporal_inconsistency"
    assert "genuine change" in result.description.lower() or "different time" in result.description.lower()


def test_missing_timestamp_is_missing_context(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C", timestamp_value=datetime(2000, 1, 1, 9, 0))
    b = _claim(db, _doc(db, "b.txt"), numeric_value=88.0, unit="°C", timestamp_value=None)
    result = compare_claims(a, b)
    assert result is not None
    assert result.conflict_type == "missing_context"


def test_unit_normalization_mismatch(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C")
    b = _claim(db, _doc(db, "b.txt"), numeric_value=65.0, unit="mm")
    result = compare_claims(a, b)
    # Different units -> missing-context, not a value contradiction.
    assert result is not None
    assert result.conflict_type == "missing_context"


def test_direct_contradiction_state_claims(db):
    a = _claim(db, _doc(db, "a.txt"), claim_type="state", predicate="state_observed", polarity="affirmative", object_value="present", unit="")
    b = _claim(db, _doc(db, "b.txt"), claim_type="state", predicate="state_observed", polarity="negative", object_value="absent", unit="")
    result = compare_claims(a, b)
    assert result is not None
    assert result.conflict_type == "direct_contradiction"
    assert result.severity == "high"


def test_same_document_never_conflicts(db):
    doc = _doc(db, "a.txt")
    a = _claim(db, doc, numeric_value=65.0, unit="°C")
    b = _claim(db, doc, numeric_value=88.0, unit="°C")
    assert compare_claims(a, b) is None


def test_detect_conflicts_returns_pairs(db):
    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C")
    b = _claim(db, _doc(db, "b.txt"), numeric_value=88.0, unit="°C")
    c = _claim(db, _doc(db, "c.txt"), numeric_value=72.0, unit="°C")
    results = detect_conflicts([a, b, c])
    assert len(results) >= 2


def test_duplicate_prevention(db):
    from app.blackboard.blackboard_service import Blackboard

    a = _claim(db, _doc(db, "a.txt"), numeric_value=65.0, unit="°C")
    b = _claim(db, _doc(db, "b.txt"), numeric_value=88.0, unit="°C")
    bb = Blackboard(db)
    bb.add_conflict(claim_a_id=a.id, claim_b_id=b.id, conflict_type="numerical_disagreement", description="d", severity="high")
    bb.commit()
    assert conflict_exists(db, a.id, b.id, "numerical_disagreement") is True
    assert conflict_exists(db, b.id, a.id, "numerical_disagreement") is True
