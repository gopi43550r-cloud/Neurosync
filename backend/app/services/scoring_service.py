"""Explainable evidence and confidence scoring.

This module implements transparent, documented heuristics. Scores are NOT
statistically calibrated probabilities; they are bounded support indicators.
Repeated claims from the same source are not treated as independent
corroboration (source independence is tracked via document_id).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Evidence, Hypothesis

# Severity weights used by scheduling and conclusion strength.
SEVERITY_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}

# Baseline reliability by evidence origin.
ORIGIN_RELIABILITY = {
    "document": 0.6,
    "user": 0.55,
    "inferred": 0.35,
}

# Reliability bonus by evidence type.
EVIDENCE_TYPE_RELIABILITY = {
    "calibration_record": 0.85,
    "timestamp": 0.75,
    "measurement": 0.7,
    "document_statement": 0.6,
    "contextual": 0.5,
    "user_supplied": 0.55,
    "missing": 0.2,
}


@dataclass
class HypothesisScore:
    support_score: float
    confidence: float
    status: str
    explanation: str
    supporting_ids: list[int] = field(default_factory=list)
    contradicting_ids: list[int] = field(default_factory=list)
    distinct_sources: int = 0
    supporting_weight: float = 0.0
    contradicting_weight: float = 0.0
    has_direct_evidence: bool = False


def evidence_weight(evidence: Evidence) -> float:
    """Combined weight of a single evidence item (0..1)."""
    base = (
        0.40 * float(evidence.relevance_score)
        + 0.35 * float(evidence.reliability_score)
        + 0.25 * float(evidence.directness)
    )
    return max(0.0, min(1.0, base))


def score_hypothesis(session: Session, hypothesis: Hypothesis) -> HypothesisScore:
    """Score one hypothesis against its evidence.

    Formula (normalized to 0..1 support):
        support = sum(positive_weights) - sum(negative_weights) * 0.75
        support = clamp(support, -1, 1) rescaled to [0,1] via (support+1)/2
    Direct evidence counts more than inferred evidence (via weight).
    Duplicate evidence from the same document is down-weighted to avoid
    counting a single source as independent corroboration.
    """
    items = [e for e in session.query(Evidence).filter(Evidence.conflict_id == hypothesis.conflict_id).all()]

    supporting: list[Evidence] = []
    contradicting: list[Evidence] = []
    for e in items:
        if e.supports_hypothesis_id == hypothesis.id:
            supporting.append(e)
        if e.contradicts_hypothesis_id == hypothesis.id:
            contradicting.append(e)

    seen_sources: dict[str, int] = {}
    pos = 0.0
    for e in supporting:
        w = evidence_weight(e)
        key = f"doc-{e.document_id}" if e.document_id else f"ev-{e.id}"
        dup_index = seen_sources.get(key, 0)
        seen_sources[key] = dup_index + 1
        # Down-weight repeated evidence from the same source.
        w *= 1.0 / (1.0 + 0.5 * dup_index)
        pos += w

    neg = 0.0
    for e in contradicting:
        neg += evidence_weight(e)

    raw = pos - 0.75 * neg
    # Map unbounded-ish raw to 0..1 with a soft saturation.
    support = raw / (raw + 1.0) if raw >= 0 else raw / (abs(raw) + 1.0)
    support = max(-1.0, min(1.0, support))
    support_score = round((support + 1.0) / 2.0, 3)

    distinct_sources = len(seen_sources)
    has_direct = any(e.directness >= 0.6 for e in supporting)
    has_negative = neg > 0

    if not supporting and not contradicting:
        status = "inconclusive"
    elif pos > 0 and neg / (pos + 1e-9) > 1.5:
        status = "contradicted"
    elif support_score >= 0.62 and has_direct:
        status = "supported"
    elif has_negative and pos > 0:
        status = "inconclusive"
    elif support_score >= 0.55:
        status = "supported"
    else:
        status = "inconclusive"

    if distinct_sources <= 1 and status == "supported":
        status = "review_required"

    confidence = round(min(0.95, support_score * 0.8 + 0.1 * min(distinct_sources, 3)), 3)

    explanation = (
        f"{len(supporting)} supporting item(s) and {len(contradicting)} contradicting item(s) "
        f"across {distinct_sources} distinct source(s). Composite support={support_score:.2f}, "
        f"status={status}. Scores are bounded support indicators, not calibrated probabilities."
    )
    return HypothesisScore(
        support_score=support_score,
        confidence=confidence,
        status=status,
        explanation=explanation,
        supporting_ids=[e.id for e in supporting],
        contradicting_ids=[e.id for e in contradicting],
        distinct_sources=distinct_sources,
        supporting_weight=round(pos, 4),
        contradicting_weight=round(neg, 4),
        has_direct_evidence=has_direct,
    )


def normalize_severity(severity: str) -> float:
    return SEVERITY_WEIGHT.get(severity, 0.5)


def scheduler_priority(
    severity: str,
    uncertainty: float,
    evidence_gap: float,
    info_gain: float,
    weights: dict[str, float],
) -> float:
    """Transparent scheduling heuristic normalized to 0..100.

    Priority = 100 * ( w_sev*Severity + w_unc*Uncertainty
                       + w_gap*EvidenceGap + w_gain*InfoGain )
    All inputs are expected in 0..1. This is a heuristic, not an optimal policy.
    """
    sev = normalize_severity(severity)
    score = (
        weights["severity"] * sev
        + weights["uncertainty"] * max(0.0, min(1.0, uncertainty))
        + weights["evidence_gap"] * max(0.0, min(1.0, evidence_gap))
        + weights["info_gain"] * max(0.0, min(1.0, info_gain))
    )
    return round(100.0 * max(0.0, min(1.0, score)), 2)
