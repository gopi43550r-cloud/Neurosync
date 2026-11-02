"""Transparent, multi-factor evidence assessment.

Every factor is computed **only** from data actually stored in the database.
Nothing is invented: when the information a factor needs is absent, the factor is
labelled ``unknown`` (or ``not applicable``) and the missing input is listed in
``missing_information``.

The assessment is a *bounded support indicator*, not a calibrated probability,
and it is **not** a claim that a source is trustworthy. Source reliability is
reported as ``unknown`` unless the evidence was explicitly supplied by a user,
because NeuroSync stores no verified source-trust ratings.

Formula (documented and surfaced to the client):

    overall = 0.35*relevance + 0.25*provenance + 0.15*recency
            + 0.15*completeness + 0.10*corroboration
    overall *= 0.85 when contradicting evidence exists for the same hypothesis
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Claim, Document, Evidence

FORMULA = (
    "overall = 0.35*relevance + 0.25*provenance + 0.15*recency "
    "+ 0.15*completeness + 0.10*corroboration; multiplied by 0.85 when "
    "contradicting evidence exists for the same hypothesis."
)

CAVEAT = (
    "This is a bounded support indicator derived from stored fields, not a "
    "calibrated probability. A high score does not certify that the source is "
    "trustworthy."
)

FACTOR_WEIGHTS = {
    "relevance": 0.35,
    "provenance": 0.25,
    "recency": 0.15,
    "completeness": 0.15,
    "corroboration": 0.10,
}


def _as_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _band(value: float, high: float, medium: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def build_context(db: Session, evidence_list: list[Evidence]) -> dict:
    """Batch-load the cross-record data the assessment factors need."""
    doc_ids = {e.document_id for e in evidence_list if e.document_id}
    claim_ids = {e.claim_id for e in evidence_list if e.claim_id}
    hyp_ids: set[int] = set()
    for e in evidence_list:
        if e.supports_hypothesis_id:
            hyp_ids.add(e.supports_hypothesis_id)
        if e.contradicts_hypothesis_id:
            hyp_ids.add(e.contradicts_hypothesis_id)

    doc_status: dict[int, str] = {}
    doc_processed: dict[int, datetime | None] = {}
    if doc_ids:
        for did, status, processed in db.execute(
            select(Document.id, Document.status, Document.processed_at).where(Document.id.in_(doc_ids))
        ).all():
            doc_status[did] = status
            doc_processed[did] = processed

    claim_ts: dict[int, datetime | None] = {}
    if claim_ids:
        for cid, ts in db.execute(
            select(Claim.id, Claim.timestamp_value).where(Claim.id.in_(claim_ids))
        ).all():
            claim_ts[cid] = ts

    support_docs: dict[int, set[str]] = defaultdict(set)
    contradict_docs: dict[int, set[str]] = defaultdict(set)
    if hyp_ids:
        rows = db.execute(
            select(
                Evidence.supports_hypothesis_id,
                Evidence.contradicts_hypothesis_id,
                Evidence.document_id,
                Evidence.id,
            ).where(
                or_(
                    Evidence.supports_hypothesis_id.in_(hyp_ids),
                    Evidence.contradicts_hypothesis_id.in_(hyp_ids),
                )
            )
        ).all()
        for supports, contradicts, doc_id, ev_id in rows:
            source_key = f"doc-{doc_id}" if doc_id else f"ev-{ev_id}"
            if supports:
                support_docs[supports].add(source_key)
            if contradicts:
                contradict_docs[contradicts].add(source_key)

    return {
        "doc_status": doc_status,
        "doc_processed": doc_processed,
        "claim_ts": claim_ts,
        "support_docs": support_docs,
        "contradict_docs": contradict_docs,
    }


def _factor(value: float, label: str, explanation: str) -> dict:
    return {
        "value": round(float(value), 3),
        "label": label,
        "explanation": explanation,
    }


def assess(ev: Evidence, ctx: dict, *, now: datetime | None = None) -> dict:
    """Return an inspectable assessment for a single evidence item."""
    now = _as_naive(now) or datetime.now(timezone.utc).replace(tzinfo=None)
    missing: list[str] = []
    factors: dict[str, dict] = {}

    # ---------------------------------------------------------- relevance
    relevance = float(ev.relevance_score)
    factors["relevance"] = _factor(
        relevance,
        _band(relevance, 0.7, 0.4),
        "Relevance to the conflicted claim, as recorded when the evidence was entered.",
    )

    # --------------------------------------------------------- provenance
    status = ctx["doc_status"].get(ev.document_id)
    if ev.origin == "document" and ev.document_id and status == "processed":
        provenance, plabel = 0.80, "linked, processed document"
    elif ev.origin == "document" and ev.document_id:
        provenance, plabel = 0.60, f"linked document (status: {status or 'unknown'})"
    elif ev.origin == "user":
        provenance, plabel = 0.50, "user-supplied"
    elif ev.origin == "inferred":
        provenance, plabel = 0.35, "inferred by an agent"
    else:
        provenance, plabel = 0.30, "no linked source"
    if ev.origin == "document" and not ev.document_id:
        missing.append("No linked source document.")
    factors["provenance"] = _factor(
        provenance,
        plabel,
        "Origin of the item and whether it is linked to a stored document.",
    )

    # ------------------------------------------------------------- recency
    # Recency reflects the *source* timestamp (the claim's stated time or the
    # source document's processing time). The evidence record's own creation time
    # is not used, because it says nothing about how fresh the source is.
    ts = ctx["claim_ts"].get(ev.claim_id) or ctx["doc_processed"].get(ev.document_id)
    ts = _as_naive(ts)
    if ts is None:
        recency, rlabel = 0.5, "unknown"
        missing.append("No source timestamp available to judge recency.")
    else:
        age_days = max(0, (now - ts).days)
        if age_days <= 1:
            recency, rlabel = 1.0, "current"
        elif age_days <= 7:
            recency, rlabel = 0.8, "recent"
        elif age_days <= 30:
            recency, rlabel = 0.5, "moderate"
        elif age_days <= 180:
            recency, rlabel = 0.3, "dated"
        else:
            recency, rlabel = 0.15, "stale"
    factors["recency"] = _factor(
        recency,
        rlabel,
        "Freshness of the source timestamp (claim time or source document).",
    )

    # -------------------------------------------------------- completeness
    checks = {
        "description": bool(ev.description and len(ev.description) >= 20),
        "source_location": bool(ev.source_location),
        "source_reference": bool(ev.source_reference),
        "linked_document": bool(ev.document_id),
        "linked_claim": bool(ev.claim_id),
    }
    present = sum(1 for ok in checks.values() if ok)
    completeness = present / len(checks)
    for name, ok in checks.items():
        if not ok:
            missing.append(f"Missing {name.replace('_', ' ')}.")
    factors["completeness"] = _factor(
        completeness,
        _band(completeness, 0.8, 0.5),
        f"{present}/{len(checks)} expected provenance fields are present.",
    )

    # -------------------------------------------------------- corroboration
    if ev.supports_hypothesis_id:
        distinct = len(ctx["support_docs"].get(ev.supports_hypothesis_id, set()))
        corroboration = _clamp(min(max(distinct - 1, 0), 3) / 3.0)
        corro_label = (
            "single source" if distinct <= 1 else f"{distinct} distinct sources"
        )
        corro_expl = "Distinct sources supporting the same hypothesis (self excluded)."
    else:
        corroboration = 0.0
        corro_label = "not applicable"
        corro_expl = "Evidence is not linked to a hypothesis, so corroboration cannot be assessed."
        missing.append("Not linked to a hypothesis; corroboration not assessable.")
    factors["corroboration"] = _factor(corroboration, corro_label, corro_expl)

    # -------------------------------------------------- contradictory evidence
    has_contradiction = bool(
        ev.supports_hypothesis_id
        and ctx["contradict_docs"].get(ev.supports_hypothesis_id)
    )
    factors["contradictory_evidence"] = {
        "value": 1.0 if has_contradiction else 0.0,
        "label": "present" if has_contradiction else "none recorded",
        "explanation": (
            "Contradicting evidence exists for the same hypothesis; the overall score is discounted."
            if has_contradiction
            else "No contradicting evidence is recorded for the same hypothesis."
        ),
    }

    # -------------------------------------------------------------- overall
    overall = (
        FACTOR_WEIGHTS["relevance"] * relevance
        + FACTOR_WEIGHTS["provenance"] * provenance
        + FACTOR_WEIGHTS["recency"] * recency
        + FACTOR_WEIGHTS["completeness"] * completeness
        + FACTOR_WEIGHTS["corroboration"] * corroboration
    )
    if has_contradiction:
        overall *= 0.85
    overall = round(_clamp(overall), 3)

    return {
        "factors": factors,
        "source_reliability": {
            "label": "unknown",
            "heuristic_indicator": round(float(ev.reliability_score), 3),
            "note": (
                "No verified source-trust rating is stored. The stored indicator is a "
                "type/origin heuristic, not an assessment of the source itself."
            ),
        },
        "overall_score": overall,
        "overall_label": _band(overall, 0.65, 0.45),
        "missing_information": missing,
        "formula": FORMULA,
        "caveat": CAVEAT,
    }


def assess_many(db: Session, evidence_list: list[Evidence]) -> dict[int, dict]:
    """Assess a batch of evidence with a bounded number of queries."""
    if not evidence_list:
        return {}
    ctx = build_context(db, evidence_list)
    now = datetime.now(timezone.utc)
    return {ev.id: assess(ev, ctx, now=now) for ev in evidence_list}
