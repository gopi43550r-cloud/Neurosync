"""Deterministic conflict detection.

Distinguishes direct contradictions from measurements that merely differ.
Considers units, timestamps and claim types. Does not classify every numerical
difference as a contradiction. Duplicate conflicts are never created.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Claim, Conflict

MEASUREMENT_TOLERANCE = 0.02  # 2% relative difference is treated as agreement

# A gap of at least this many minutes means the readings may reflect a genuine
# change over time rather than a contemporaneous contradiction.
MIN_TEMPORAL_GAP_MINUTES = 30

# Temperature units the detector can safely convert between. Anything else with
# differing units is treated as a missing-context comparison (not a value clash).
_TEMP_CONVERTERS = {
    "°C": lambda v: v,
    "°F": lambda v: (v - 32.0) * 5.0 / 9.0,
    "K": lambda v: v - 273.15,
}


def _canonical_measurement(unit: str, value: float) -> tuple[str, float] | None:
    """Map a value to a canonical (dimension, value) pair for comparison.

    Returns ``None`` for units the detector cannot convert, so the caller falls
    back to a missing-context comparison instead of guessing.
    """
    converter = _TEMP_CONVERTERS.get(unit)
    if converter is None:
        return None
    try:
        return ("temperature", converter(float(value)))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


@dataclass
class DetectedConflict:
    claim_a_id: int
    claim_b_id: int
    conflict_type: str
    description: str
    severity: str
    confidence: float
    detection_method: str = "rule_based"
    meta: dict | None = None


def _relative_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def _property(claim: Claim) -> str:
    """The property asserted by a claim (its predicate), falling back to subject."""
    return claim.predicate or claim.subject


def _meta(claim: Claim, reason: str, **extra) -> dict:
    data = {"reason": reason, "subject": claim.subject, "property": _property(claim)}
    data.update(extra)
    return data


def _time_gap_minutes(a: Claim, b: Claim) -> float | None:
    if a.timestamp_value and b.timestamp_value:
        delta = abs((a.timestamp_value - b.timestamp_value).total_seconds()) / 60.0
        return delta
    return None


def compare_claims(a: Claim, b: Claim) -> DetectedConflict | None:
    """Return a detected conflict for a claim pair, or None if compatible.

    Two claims can only contradict one another when they concern the *same
    subject* **and** the *same property* (predicate). A temperature reading and a
    pressure reading of the same machine are different facts, not a conflict.
    """
    if not a.subject or not b.subject or a.subject != b.subject:
        return None
    if _property(a) != _property(b):
        return None
    if a.id == b.id or a.document_id == b.document_id:
        # Claims from the same document are not treated as cross-source conflict.
        return None

    # --- measurement vs measurement ---
    if a.claim_type == "measurement" and b.claim_type == "measurement":
        value_a, value_b = a.numeric_value, b.numeric_value
        if a.unit != b.unit or not a.unit or not b.unit:
            if a.numeric_value is None or b.numeric_value is None:
                return None
            # Try to reconcile different units of the same physical quantity
            # (e.g. 100°F vs 37.8°C) before declaring them incomparable.
            conv_a = _canonical_measurement(a.unit, a.numeric_value) if a.unit else None
            conv_b = _canonical_measurement(b.unit, b.numeric_value) if b.unit else None
            if conv_a and conv_b and conv_a[0] == conv_b[0]:
                value_a, value_b = conv_a[1], conv_b[1]
            else:
                # Different or missing units that cannot be converted: flag as
                # missing-context, not a value conflict.
                return DetectedConflict(
                    claim_a_id=a.id,
                    claim_b_id=b.id,
                    conflict_type="missing_context",
                    description=(
                        f"Measurements of '{a.subject}' use different or missing units "
                        f"({a.unit or 'unspecified'} vs {b.unit or 'unspecified'}); "
                        "they cannot be directly compared without unit context."
                    ),
                    severity="low",
                    confidence=0.45,
                    meta=_meta(a, "unit_mismatch", units=[a.unit or None, b.unit or None]),
                )

        if value_a is None or value_b is None:
            return None

        diff = _relative_diff(value_a, value_b)
        if diff <= MEASUREMENT_TOLERANCE:
            return None  # values agree within tolerance (after any conversion)

        gap = _time_gap_minutes(a, b)

        if gap is not None and gap >= MIN_TEMPORAL_GAP_MINUTES:
            # Different times: could be genuine change, not necessarily contradictory.
            return DetectedConflict(
                claim_a_id=a.id,
                claim_b_id=b.id,
                conflict_type="temporal_inconsistency",
                description=(
                    f"'{a.subject}' is {a.numeric_value:g}{a.unit} in one report and "
                    f"{b.numeric_value:g}{b.unit} in another, measured about "
                    f"{gap:.0f} minutes apart. These may reflect a genuine change over "
                    "time rather than contradictory measurements, but the difference is "
                    "large enough to warrant investigation."
                ),
                severity="medium",
                confidence=0.6,
                meta=_meta(
                    a,
                    "different_time",
                    time_gap_minutes=round(gap, 1),
                    relative_diff=round(diff, 3),
                ),
            )

        if (a.timestamp_value is None) ^ (b.timestamp_value is None):
            return DetectedConflict(
                claim_a_id=a.id,
                claim_b_id=b.id,
                conflict_type="missing_context",
                description=(
                    f"'{a.subject}' measurements differ ({a.numeric_value:g}{a.unit} vs "
                    f"{b.numeric_value:g}{b.unit}) but only one report records a timestamp, "
                    "so it is unclear whether the readings are contemporaneous."
                ),
                severity="medium",
                confidence=0.5,
                meta=_meta(a, "missing_timestamp", relative_diff=round(diff, 3)),
            )

        severity = "high" if diff > 0.25 else "medium"
        return DetectedConflict(
            claim_a_id=a.id,
            claim_b_id=b.id,
            conflict_type="numerical_disagreement",
            description=(
                f"'{a.subject}' is reported as {a.numeric_value:g}{a.unit} and "
                f"{b.numeric_value:g}{b.unit} within the same time period with no "
                f"distinguishing context ({diff * 100:.0f}% difference)."
            ),
            severity=severity,
            confidence=0.7,
            meta=_meta(a, "contemporaneous_disagreement", relative_diff=round(diff, 3)),
        )

    # --- state vs state ---
    if a.claim_type == "state" and b.claim_type == "state":
        if a.polarity != b.polarity:
            return DetectedConflict(
                claim_a_id=a.id,
                claim_b_id=b.id,
                conflict_type="direct_contradiction",
                description=(
                    f"One report states '{a.subject}' was {a.object_value}, while another "
                    f"states it was {b.object_value}. These assertions are directly opposed."
                ),
                severity="high",
                confidence=0.75,
                meta=_meta(a, "opposite_polarity"),
            )
        if a.object_value and b.object_value and a.object_value != b.object_value:
            return DetectedConflict(
                claim_a_id=a.id,
                claim_b_id=b.id,
                conflict_type="semantic_inconsistency",
                description=(
                    f"Reports describe the '{a.subject}' status differently: "
                    f"'{a.object_value}' vs '{b.object_value}'."
                ),
                severity="medium",
                confidence=0.5,
                meta=_meta(a, "different_state_values"),
            )
    return None


def detect_conflicts(claims: list[Claim]) -> list[DetectedConflict]:
    """Compare relevant claim pairs (same subject) across documents."""
    detected: list[DetectedConflict] = []
    by_subject: dict[str, list[Claim]] = {}
    for c in claims:
        if c.subject:
            by_subject.setdefault(c.subject, []).append(c)

    for group in by_subject.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                result = compare_claims(group[i], group[j])
                if result:
                    detected.append(result)
    return detected


def conflict_exists(db: Session, claim_a_id: int, claim_b_id: int, conflict_type: str) -> bool:
    stmt = select(Conflict).where(
        Conflict.conflict_type == conflict_type,
        or_(
            (Conflict.claim_a_id == claim_a_id) & (Conflict.claim_b_id == claim_b_id),
            (Conflict.claim_a_id == claim_b_id) & (Conflict.claim_b_id == claim_a_id),
        ),
    )
    return db.execute(stmt).scalars().first() is not None
