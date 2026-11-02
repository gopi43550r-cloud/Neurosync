"""Report generation: structured, auditable investigation reports.

A report is built *only* from persisted investigation records (documents,
claims, conflicts, evidence, hypotheses, conclusions, human reviews, agent
activity and the audit trail). Nothing is inferred or invented: every statement
in the report is backed by a stored row and carries a link back to its source.

Design notes
------------
* ``build_report`` returns a flat ``sections`` list (heading/body/items) for
  backwards compatibility *and* a rich ``json_data`` document with typed,
  linked records. The markdown export and the PDF export are rendered from the
  same sections.
* Untrusted text (claim text, document names, descriptions, reviewer notes) is
  sanitised everywhere: control characters are stripped for every artifact, and
  HTML-significant characters are escaped in the markdown and PDF artifacts so a
  report can never inject markup into a viewer.
* Observed facts (documents, claims, conflicts, document/user evidence) are
  distinguished from inferred explanations (hypotheses, inferred evidence).
* No secrets or storage paths are emitted - only display names, identifiers and
  links.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import (
    AgentActivity,
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    HumanReview,
    Hypothesis,
    Investigation,
)
from . import ranking_service
from .investigation_service import activity_for
from .scoring_service import evidence_weight

SCHEMA_VERSION = 2

STOP_REASON_TEXT = {
    "no_unresolved_conflicts": "Stopped because no unresolved conflicts remained.",
    "no_useful_actions_remaining": "Stopped because no eligible agent could provide further useful information.",
    "iteration_limit_reached": "Stopped because the configured iteration limit was reached.",
    "execution_limit_reached": "Stopped because the configured execution limit was reached.",
    "cancelled_by_user": "Stopped because the user cancelled the investigation.",
    "error_prevented_continuation": "Stopped because an error prevented safe continuation.",
    "human_review_required": "Stopped because human review is required.",
    "investigation_converged": "Stopped because the investigation converged on a conclusion.",
}

CONFIDENCE_INTERPRETATION = (
    "Confidence is the mean of the per-conflict conclusion support scores. It is a "
    "bounded support indicator derived from documented evidence weights, NOT a "
    "statistically calibrated probability. A higher value means more (reliable, "
    "direct, source-diverse) supporting evidence relative to contradicting evidence; "
    "it does not mean 'X% likely to be true'."
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# --------------------------------------------------------------------------- text
def safe_text(value: object, *, limit: int | None = None) -> str:
    """Return control-stripped, whitespace-normalised text for any artifact."""
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_CHARS.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "\u2026"
    return text


def escape_text(value: object, *, limit: int | None = None) -> str:
    """Sanitise *and* HTML-escape text for the markdown / PDF artifacts."""
    return html.escape(safe_text(value, limit=limit), quote=True)


def _loads(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _link_document(document_id: int | None) -> str | None:
    return f"/documents/{document_id}" if document_id else None


def _link_conflict(conflict_id: int | None) -> str | None:
    return f"/conflicts/{conflict_id}" if conflict_id else None


def _link_investigation(investigation_id: int | None) -> str | None:
    return f"/investigations/{investigation_id}" if investigation_id else None


def _origin_label(origin: str | None) -> str:
    """Classify a record as an observed fact or an inferred explanation."""
    if origin == "inferred":
        return "inferred"
    if origin in ("document", "user", "user_supplied"):
        return "observed"
    return origin or "observed"


# --------------------------------------------------------------------------- build
def build_report(db: Session, investigation: Investigation) -> dict:
    documents = list(investigation.documents)
    conflicts = list(investigation.conflicts)
    activity = activity_for(db, investigation.id)

    document_by_id = {d.id: d for d in documents}

    # --- claims -----------------------------------------------------------
    claims: list[Claim] = []
    if document_by_id:
        claims = (
            db.query(Claim)
            .filter(Claim.document_id.in_(list(document_by_id.keys())))
            .order_by(Claim.document_id, Claim.id)
            .all()
        )
    claim_by_id = {c.id: c for c in claims}

    # --- evidence / hypotheses / conclusions ------------------------------
    conflict_ids = [c.id for c in conflicts]
    all_evidence: list[Evidence] = []
    all_hypotheses: list[Hypothesis] = []
    if conflict_ids:
        all_evidence = (
            db.query(Evidence)
            .filter(Evidence.conflict_id.in_(conflict_ids))
            .order_by(Evidence.id)
            .all()
        )
        all_hypotheses = (
            db.query(Hypothesis)
            .filter(Hypothesis.conflict_id.in_(conflict_ids))
            .order_by(Hypothesis.id)
            .all()
        )
    all_conclusions = (
        db.query(Conclusion)
        .filter(Conclusion.investigation_id == investigation.id)
        .order_by(Conclusion.id)
        .all()
    )
    evidence_by_id = {e.id: e for e in all_evidence}

    confidence = (
        round(sum(c.confidence for c in all_conclusions) / len(all_conclusions), 3)
        if all_conclusions
        else 0.0
    )

    # --- reviews ----------------------------------------------------------
    reviews = (
        db.query(HumanReview)
        .filter(HumanReview.investigation_id == investigation.id)
        .order_by(HumanReview.id)
        .all()
    )

    # --- audit trail ------------------------------------------------------
    from . import audit_service

    audit_events = audit_service.list_events(db, investigation_id=investigation.id)

    # --- unresolved / limitations / gaps ----------------------------------
    unresolved: list[str] = []
    limitations: list[str] = []
    for c in all_conclusions:
        unresolved.extend(_loads(c.unresolved_questions))
        limitations.extend(_loads(c.limitations))
    unresolved = list(dict.fromkeys(u for u in unresolved if u))
    limitations = list(dict.fromkeys(u for u in limitations if u))

    evidence_gaps: list[str] = []
    for c in conflicts:
        for gap in ranking_service.missing_evidence(db, c.id):
            evidence_gaps.append(f"Conflict {c.id}: {gap}")
    evidence_gaps = list(dict.fromkeys(evidence_gaps))

    # --- serialise records ------------------------------------------------
    doc_out = [_document_out(d, claim_by_id) for d in documents]
    claim_out = [_claim_out(c, document_by_id) for c in claims]
    conflict_out = [_conflict_out(c, claim_by_id, document_by_id) for c in conflicts]
    evidence_out = [
        _evidence_out(e, document_by_id, conflict_ids) for e in all_evidence
    ]
    hypothesis_out = [
        _hypothesis_out(h, evidence_by_id) for h in all_hypotheses
    ]
    conclusion_out = [
        _conclusion_out(c, evidence_by_id, conflict_ids) for c in all_conclusions
    ]
    review_out = [_review_out(r) for r in reviews]

    evidence_by_claim = _evidence_by_claim(conflicts, claims, all_evidence, document_by_id)
    verification_out = _verification_out(all_evidence, document_by_id, conflict_ids)

    # --- agent activity summary ------------------------------------------
    activity_summary = _activity_summary(activity)

    # --- hypothesis ranking (flat, for the ranking section) ---------------
    ranking_items: list[str] = []
    ranking_data: list[dict] = []
    for c in conflicts:
        for item in ranking_service.rank_hypotheses(db, c.id):
            ranking_data.append(item)
            margin = (
                f", margin to next={item['margin_to_next']:.2f}"
                if item.get("margin_to_next") is not None
                else ""
            )
            criteria = item["criteria"]
            ranking_items.append(
                f"Conflict {c.id} rank {item['rank']}: \"{item['title']}\" "
                f"(support={item['support_score']:.2f}, confidence={item['confidence']:.2f}, "
                f"+weight={criteria['supporting_evidence_weight']:.2f}, "
                f"-weight={criteria['contradicting_evidence_weight']:.2f}, "
                f"distinct sources={criteria['distinct_supporting_sources']}, "
                f"direct evidence={criteria['has_direct_supporting_evidence']}{margin})"
            )

    # --- human review status ---------------------------------------------
    conflicts_awaiting = [c for c in conflicts if c.status == "human_review"]
    human_review_status = {
        "required": bool(conflicts_awaiting),
        "conflicts_awaiting_review": [c.id for c in conflicts_awaiting],
        "decisions_recorded": len(reviews),
        "status": (
            "reviewed"
            if reviews
            else "awaiting review"
            if conflicts_awaiting
            else "not required"
        ),
    }

    # --- warnings (data completeness) ------------------------------------
    warnings = _warnings(documents, claims, conflicts, all_evidence, all_conclusions, reviews)

    timestamps = {
        "created_at": _iso(investigation.created_at),
        "started_at": _iso(investigation.started_at),
        "completed_at": _iso(investigation.completed_at),
        "updated_at": _iso(investigation.updated_at),
        "generated_at": _iso(datetime.now(timezone.utc)),
        "duration_seconds": _duration_seconds(investigation),
    }

    investigation_out = {
        "id": investigation.id,
        "title": safe_text(investigation.name),
        "question": safe_text(investigation.research_question)
        or "No explicit research question was provided.",
        "status": investigation.status,
        "stop_reason": investigation.stop_reason,
        "stop_reason_text": STOP_REASON_TEXT.get(
            investigation.stop_reason, safe_text(investigation.stop_reason) or "Not recorded."
        ),
        "iteration_count": investigation.iteration_count,
        "iteration_limit": investigation.iteration_limit,
        "is_demo": bool(investigation.is_demo),
        "link": _link_investigation(investigation.id),
    }

    data: dict = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamps["generated_at"],
        "generator": "NeuroSync automated evidence-driven investigation",
        "investigation": investigation_out,
        "documents": doc_out,
        "claims": claim_out,
        "conflicts": conflict_out,
        "evidence": evidence_out,
        "evidence_by_claim": evidence_by_claim,
        "hypotheses": hypothesis_out,
        "verification": verification_out,
        "conclusions": conclusion_out,
        "confidence": {
            "value": confidence,
            "basis": "Mean of per-conflict conclusion support scores.",
            "interpretation": CONFIDENCE_INTERPRETATION,
        },
        "human_reviews": review_out,
        "human_review_status": human_review_status,
        "agent_activity": activity_summary,
        "audit_trail": [
            {
                "id": a.id,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "action": a.action,
                "actor": a.actor,
                "summary": safe_text(a.summary, limit=500),
                "created_at": _iso(a.created_at),
            }
            for a in audit_events
        ],
        "evidence_gaps": evidence_gaps,
        "unresolved_questions": unresolved,
        "limitations": limitations,
        "recommendations": _recommendations(conflicts, all_conclusions),
        "timestamps": timestamps,
        "warnings": warnings,
    }

    sections = _build_sections(
        investigation=investigation,
        investigation_out=investigation_out,
        documents=documents,
        doc_out=doc_out,
        claims=claims,
        claim_out=claim_out,
        conflicts=conflicts,
        conflict_out=conflict_out,
        evidence_by_claim=evidence_by_claim,
        all_evidence=all_evidence,
        evidence_out=evidence_out,
        all_hypotheses=all_hypotheses,
        hypothesis_out=hypothesis_out,
        ranking_items=ranking_items,
        verification_out=verification_out,
        all_conclusions=all_conclusions,
        conclusion_out=conclusion_out,
        confidence=confidence,
        unresolved=unresolved,
        limitations=limitations,
        evidence_gaps=evidence_gaps,
        recommendations=_recommendations(conflicts, all_conclusions),
        reviews=reviews,
        review_out=review_out,
        human_review_status=human_review_status,
        activity_summary=activity_summary,
        audit_events=data["audit_trail"],
        timestamps=timestamps,
        warnings=warnings,
    )

    markdown = _to_markdown(investigation, sections)
    return {
        "investigation_id": investigation.id,
        "title": safe_text(investigation.name),
        "objective": safe_text(investigation.research_question),
        "generated_at": datetime.now(timezone.utc),
        "sections": sections,
        "markdown": markdown,
        "json_data": data,
        "stopping_reason": investigation_out["stop_reason_text"],
        "confidence": confidence,
        "confidence_explanation": CONFIDENCE_INTERPRETATION,
        "warnings": warnings,
        "schema_version": SCHEMA_VERSION,
    }


# --------------------------------------------------------------------------- record serialisers
def _document_out(doc: Document, claim_by_id: dict[int, Claim]) -> dict:
    claim_count = sum(1 for c in claim_by_id.values() if c.document_id == doc.id)
    return {
        "id": doc.id,
        "filename": safe_text(doc.filename),
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "status": doc.status,
        "is_demo": bool(doc.is_demo),
        "uploaded_at": _iso(doc.uploaded_at),
        "processed_at": _iso(doc.processed_at),
        "claim_count": claim_count,
        "link": _link_document(doc.id),
        "kind": "observed",
    }


def _claim_out(claim: Claim, document_by_id: dict[int, Document]) -> dict:
    doc = document_by_id.get(claim.document_id)
    return {
        "id": claim.id,
        "document_id": claim.document_id,
        "document_filename": safe_text(doc.filename) if doc else None,
        "document_link": _link_document(claim.document_id),
        "claim_text": safe_text(claim.claim_text),
        "subject": safe_text(claim.subject),
        "predicate": safe_text(claim.predicate),
        "object_value": safe_text(claim.object_value),
        "numeric_value": claim.numeric_value,
        "unit": safe_text(claim.unit),
        "polarity": claim.polarity,
        "claim_type": claim.claim_type,
        "source_reference": safe_text(claim.source_reference),
        "source_location": safe_text(claim.source_location),
        "timestamp_value": _iso(claim.timestamp_value),
        "confidence": claim.confidence,
        "created_at": _iso(claim.created_at),
        "kind": "observed",
    }


def _conflict_out(
    conflict: Conflict,
    claim_by_id: dict[int, Claim],
    document_by_id: dict[int, Document],
) -> dict:
    def _claim_ref(claim_id: int | None) -> dict | None:
        claim = claim_by_id.get(claim_id) if claim_id else None
        if claim is None:
            return None
        doc = document_by_id.get(claim.document_id)
        return {
            "id": claim.id,
            "text": safe_text(claim.claim_text),
            "document_id": claim.document_id,
            "document_filename": safe_text(doc.filename) if doc else None,
            "document_link": _link_document(claim.document_id),
        }

    return {
        "id": conflict.id,
        "type": conflict.conflict_type,
        "severity": conflict.severity,
        "status": conflict.status,
        "description": safe_text(conflict.description),
        "detection_method": conflict.detection_method,
        "confidence": conflict.confidence,
        "created_at": _iso(conflict.created_at),
        "claim_a": _claim_ref(conflict.claim_a_id),
        "claim_b": _claim_ref(conflict.claim_b_id),
        "link": _link_conflict(conflict.id),
        "kind": "observed",
    }


def _evidence_out(
    evidence: Evidence, document_by_id: dict[int, Document], conflict_ids: list[int]
) -> dict:
    doc = document_by_id.get(evidence.document_id) if evidence.document_id else None
    return {
        "id": evidence.id,
        "conflict_id": evidence.conflict_id,
        "conflict_link": _link_conflict(evidence.conflict_id),
        "claim_id": evidence.claim_id,
        "document_id": evidence.document_id,
        "document_filename": safe_text(doc.filename) if doc else None,
        "document_link": _link_document(evidence.document_id),
        "evidence_type": evidence.evidence_type,
        "origin": evidence.origin,
        "kind": _origin_label(evidence.origin),
        "description": safe_text(evidence.description),
        "source_reference": safe_text(evidence.source_reference),
        "source_location": safe_text(evidence.source_location),
        "supports_hypothesis_id": evidence.supports_hypothesis_id,
        "contradicts_hypothesis_id": evidence.contradicts_hypothesis_id,
        "relevance_score": evidence.relevance_score,
        "reliability_score": evidence.reliability_score,
        "directness": evidence.directness,
        "weight": round(evidence_weight(evidence), 3),
        "verification_status": evidence.verification_status,
        "created_at": _iso(evidence.created_at),
    }


def _hypothesis_out(hypothesis: Hypothesis, evidence_by_id: dict[int, Evidence]) -> dict:
    supporting = _evidence_refs(hypothesis.supporting_evidence_ids, evidence_by_id)
    contradicting = _evidence_refs(hypothesis.contradicting_evidence_ids, evidence_by_id)
    return {
        "id": hypothesis.id,
        "conflict_id": hypothesis.conflict_id,
        "conflict_link": _link_conflict(hypothesis.conflict_id),
        "title": safe_text(hypothesis.title),
        "explanation": safe_text(hypothesis.explanation),
        "status": hypothesis.status,
        "origin": hypothesis.origin,
        "kind": "inferred",
        "support_score": hypothesis.support_score,
        "confidence": hypothesis.confidence,
        "assumptions": [safe_text(a) for a in _loads(hypothesis.assumptions)],
        "missing_information": [safe_text(a) for a in _loads(hypothesis.missing_information)],
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "created_at": _iso(hypothesis.created_at),
        "updated_at": _iso(hypothesis.updated_at),
    }


def _evidence_refs(ids_json: str, evidence_by_id: dict[int, Evidence]) -> list[dict]:
    refs = []
    for eid in _loads(ids_json):
        ev = evidence_by_id.get(int(eid)) if str(eid).isdigit() else None
        refs.append(
            {
                "id": int(eid) if str(eid).isdigit() else None,
                "exists": ev is not None,
                "description": safe_text(ev.description, limit=200) if ev else "",
                "evidence_type": ev.evidence_type if ev else None,
                "document_link": _link_document(ev.document_id) if ev else None,
            }
        )
    return refs


def _conclusion_out(
    conclusion: Conclusion,
    evidence_by_id: dict[int, Evidence],
    conflict_ids: list[int],
) -> dict:
    support_ids = [int(i) for i in _loads(conclusion.supporting_evidence_ids) if str(i).isdigit()]
    supporting = [
        {
            "id": eid,
            "exists": eid in evidence_by_id,
            "description": safe_text(evidence_by_id[eid].description, limit=200)
            if eid in evidence_by_id
            else "",
            "document_link": _link_document(evidence_by_id[eid].document_id)
            if eid in evidence_by_id
            else None,
        }
        for eid in support_ids
    ]
    return {
        "id": conclusion.id,
        "conflict_id": conclusion.conflict_id,
        "conflict_link": _link_conflict(conclusion.conflict_id),
        "decision_type": conclusion.decision_type,
        "conclusion": safe_text(conclusion.conclusion),
        "confidence": conclusion.confidence,
        "supporting_evidence_ids": support_ids,
        "supporting_evidence": supporting,
        "unresolved_questions": [safe_text(q) for q in _loads(conclusion.unresolved_questions)],
        "limitations": [safe_text(l) for l in _loads(conclusion.limitations)],
        "is_inconclusive": conclusion.decision_type in ("inconclusive", "human_review_required"),
        "created_at": _iso(conclusion.created_at),
        "superseded_by_id": conclusion.superseded_by_id,
    }


def _review_out(review: HumanReview) -> dict:
    return {
        "id": review.id,
        "conclusion_id": review.conclusion_id,
        "conflict_id": review.conflict_id,
        "decision": review.decision,
        "reviewer": safe_text(review.reviewer),
        "note": safe_text(review.note),
        "previous_decision_type": review.previous_decision_type,
        "created_at": _iso(review.created_at),
    }


def _evidence_by_claim(
    conflicts: list[Conflict],
    claims: list[Claim],
    evidence: list[Evidence],
    document_by_id: dict[int, Document],
) -> list[dict]:
    """Ground evidence for each conflict-relevant claim.

    Supporting evidence is the evidence explicitly linked to the claim
    (``Evidence.claim_id``). Contradicting evidence is the evidence explicitly
    linked to the *opposing* claim in the same recorded conflict, which is the
    only contradiction the blackboard actually asserts. No contradiction is
    invented for claims that are not part of a conflict.
    """
    claim_by_id = {c.id: c for c in claims}
    by_claim: dict[int, list[Evidence]] = {}
    for ev in evidence:
        if ev.claim_id:
            by_claim.setdefault(ev.claim_id, []).append(ev)

    def _ref(ev: Evidence) -> dict:
        doc = document_by_id.get(ev.document_id) if ev.document_id else None
        return {
            "id": ev.id,
            "description": safe_text(ev.description),
            "evidence_type": ev.evidence_type,
            "source_reference": safe_text(ev.source_reference),
            "document_id": ev.document_id,
            "document_link": _link_document(ev.document_id),
            "document_filename": safe_text(doc.filename) if doc else None,
        }

    out: list[dict] = []
    seen: set[int] = set()
    for conflict in conflicts:
        for claim_id, opposing_id in (
            (conflict.claim_a_id, conflict.claim_b_id),
            (conflict.claim_b_id, conflict.claim_a_id),
        ):
            if claim_id in seen:
                continue
            seen.add(claim_id)
            claim = claim_by_id.get(claim_id)
            out.append(
                {
                    "claim_id": claim_id,
                    "claim_text": safe_text(claim.claim_text) if claim else None,
                    "document_id": claim.document_id if claim else None,
                    "document_link": _link_document(claim.document_id) if claim else None,
                    "conflict_id": conflict.id,
                    "conflict_link": _link_conflict(conflict.id),
                    "supporting_evidence": [_ref(e) for e in by_claim.get(claim_id, [])],
                    "contradicting_evidence": [_ref(e) for e in by_claim.get(opposing_id or -1, [])],
                    "basis": (
                        f"Recorded conflict {conflict.id} places this claim against "
                        f"claim {opposing_id}." if opposing_id else "No recorded opposing claim."
                    ),
                }
            )
    return out


def _verification_out(
    evidence: list[Evidence], document_by_id: dict[int, Document], conflict_ids: list[int]
) -> list[dict]:
    out = []
    for e in evidence:
        doc = document_by_id.get(e.document_id) if e.document_id else None
        out.append(
            {
                "evidence_id": e.id,
                "evidence_type": e.evidence_type,
                "description": safe_text(e.description, limit=200),
                "verification_status": e.verification_status,
                "reliability_score": e.reliability_score,
                "relevance_score": e.relevance_score,
                "directness": e.directness,
                "weight": round(evidence_weight(e), 3),
                "document_link": _link_document(e.document_id),
                "document_filename": safe_text(doc.filename) if doc else None,
            }
        )
    return out


def _activity_summary(activity: list[AgentActivity]) -> dict:
    by_agent: dict[str, dict] = {}
    timeline = []
    for a in activity:
        bucket = by_agent.setdefault(
            a.agent_name,
            {"agent_name": a.agent_name, "actions": 0, "successes": 0, "failures": 0, "total_duration_ms": 0},
        )
        bucket["actions"] += 1
        if a.status == "success":
            bucket["successes"] += 1
        elif a.status == "failed":
            bucket["failures"] += 1
        bucket["total_duration_ms"] += a.duration_ms or 0
        timeline.append(
            {
                "id": a.id,
                "sequence": a.sequence,
                "attempt": a.attempt,
                "agent_name": a.agent_name,
                "action": safe_text(a.action),
                "input_summary": safe_text(a.input_summary, limit=300),
                "output_summary": safe_text(a.output_summary, limit=300),
                "reason": safe_text(a.reason, limit=300),
                "status": a.status,
                "duration_ms": a.duration_ms,
                "error": safe_text(a.error, limit=300) if a.status == "failed" else "",
                "created_at": _iso(a.created_at),
            }
        )
    return {
        "count": len(activity),
        "by_agent": list(by_agent.values()),
        "timeline": timeline,
    }


def _warnings(
    documents: list[Document],
    claims: list[Claim],
    conflicts: list[Conflict],
    evidence: list[Evidence],
    conclusions: list[Conclusion],
    reviews: list[HumanReview],
) -> list[str]:
    warnings: list[str] = []
    if not documents:
        warnings.append("No documents are associated with this investigation.")
    if not claims:
        warnings.append("No claims were extracted from the documents.")
    if not conflicts:
        warnings.append("No conflicts were detected; there is nothing to adjudicate.")
    if conflicts and not evidence:
        warnings.append("Conflicts exist but no evidence was recorded.")
    if conflicts and not conclusions:
        warnings.append("No conclusion has been produced for the recorded conflict(s).")
    if any(c.decision_type in ("inconclusive", "human_review_required") for c in conclusions):
        warnings.append(
            "At least one conclusion is inconclusive or requires human review; the "
            "report does not assert a definitive finding."
        )
    if any(not ev.verification_status or ev.verification_status == "unverified" for ev in evidence):
        warnings.append("Some evidence remains unverified.")
    if any(c.status == "human_review" for c in conflicts) and not reviews:
        warnings.append("A conflict is awaiting human review; no decision has been recorded yet.")
    return warnings


def _duration_seconds(investigation: Investigation) -> float | None:
    if investigation.started_at and investigation.completed_at:
        start = investigation.started_at
        end = investigation.completed_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return round((end - start).total_seconds(), 1)
    return None


def _recommendations(conflicts: list[Conflict], conclusions: list[Conclusion]) -> list[str]:
    recs = []
    for c in conflicts:
        if c.status == "human_review":
            recs.append(f"Route conflict {c.id} to a human reviewer with the attached evidence.")
        elif c.status == "inconclusive":
            recs.append(f"Collect additional information about conflict {c.id} (see unresolved questions).")
    if not recs:
        recs.append("No further action required based on the available evidence.")
    return recs


# --------------------------------------------------------------------------- sections
def _build_sections(**ctx) -> list[dict]:
    investigation: Investigation = ctx["investigation"]
    doc_out = ctx["doc_out"]
    claim_out = ctx["claim_out"]
    conflicts = ctx["conflicts"]
    conflict_out = ctx["conflict_out"]
    evidence_by_claim = ctx["evidence_by_claim"]
    all_evidence = ctx["all_evidence"]
    all_hypotheses = ctx["all_hypotheses"]
    ranking_items = ctx["ranking_items"]
    verification_out = ctx["verification_out"]
    all_conclusions = ctx["all_conclusions"]
    confidence = ctx["confidence"]
    unresolved = ctx["unresolved"]
    limitations = ctx["limitations"]
    evidence_gaps = ctx["evidence_gaps"]
    reviews = ctx["reviews"]
    human_review_status = ctx["human_review_status"]
    activity_summary = ctx["activity_summary"]
    timestamps = ctx["timestamps"]
    warnings = ctx["warnings"]

    sections: list[dict] = []

    sections.append(
        {
            "heading": "Investigation Title and Identifier",
            "body": f"{safe_text(investigation.name)} (id {investigation.id}).",
            "items": [],
        }
    )
    sections.append({"heading": "Investigation Title", "body": safe_text(investigation.name), "items": []})
    sections.append(
        {
            "heading": "Objective",
            "body": safe_text(investigation.research_question)
            or "No explicit research question was provided.",
            "items": [],
        }
    )

    # 3. documents
    sections.append(
        {
            "heading": "Documents Analyzed",
            "body": f"{len(doc_out)} document(s) were analyzed."
            + (" These are demonstration documents." if investigation.is_demo else ""),
            "items": [
                f"[{d['filename']}](/documents/{d['id']}) ({d['file_type']}, {d['file_size']} bytes, "
                f"{d['claim_count']} claim(s), status={d['status']})"
                for d in doc_out
            ],
        }
    )

    # 4. claims extracted
    sections.append(
        {
            "heading": "Claims Extracted",
            "body": f"{len(claim_out)} claim(s) were extracted and are treated as reported "
            "observations, not established facts.",
            "items": [
                f"[{c['document_filename']}](/documents/{c['document_id']}) claim {c['id']}: "
                f"\"{c['claim_text']}\""
                + (f" (numeric={c['numeric_value']}{' ' + c['unit'] if c['unit'] else ''})" if c["numeric_value"] is not None else "")
                + (f" [source: {c['source_reference']}]" if c["source_reference"] else "")
                for c in claim_out
            ][:200],
        }
    )

    # legacy observations section (kept for backwards compatibility)
    key_observations = [
        f"{c['document_filename']}: {c['claim_text']} (source: {c['source_reference']})"
        for c in claim_out
    ]
    sections.append({"heading": "Key Observations", "body": "", "items": key_observations[:50]})

    # 5. conflicts detected
    sections.append(
        {
            "heading": "Conflicting Claims",
            "body": f"{len(conflict_out)} potential conflict(s) were identified.",
            "items": [f"Conflict {c['id']}: {c['description']}" for c in conflict_out],
        }
    )
    sections.append(
        {
            "heading": "Conflict Classifications",
            "body": "",
            "items": [
                f"Conflict {c['id']}: type={c['type']}, severity={c['severity']}, status={c['status']}"
                + (f", claims {c['claim_a']['id']} vs {c['claim_b']['id']}" if c.get("claim_a") and c.get("claim_b") else "")
                for c in conflict_out
            ],
        }
    )

    # 6/7. evidence supporting / contradicting each relevant claim
    supporting_items: list[str] = []
    contradicting_items: list[str] = []
    for entry in evidence_by_claim:
        label = f"Claim {entry['claim_id']}"
        for ev in entry["supporting_evidence"]:
            supporting_items.append(
                f"{label}: evidence {ev['id']} [{ev['evidence_type']}] {ev['description']}"
                + (f" (source: {ev['document_filename']})" if ev.get("document_filename") else "")
            )
        for ev in entry["contradicting_evidence"]:
            contradicting_items.append(
                f"{label}: evidence {ev['id']} [{ev['evidence_type']}] {ev['description']} ({entry['basis']})"
                + (f" (source: {ev['document_filename']})" if ev.get("document_filename") else "")
            )
    sections.append(
        {
            "heading": "Evidence Supporting Each Relevant Claim",
            "body": "Evidence explicitly recorded against each claim that takes part in a conflict.",
            "items": supporting_items or ["No supporting evidence was recorded for the claims."],
        }
    )
    sections.append(
        {
            "heading": "Evidence Contradicting Each Relevant Claim",
            "body": "Evidence recorded against the opposing claim in each recorded conflict. No "
            "contradiction is inferred beyond what the conflict identifies.",
            "items": contradicting_items or ["No contradicting evidence was recorded."],
        }
    )

    # 8. competing hypotheses
    sections.append(
        {
            "heading": "Competing Hypotheses",
            "body": f"{len(all_hypotheses)} explanation(s) were proposed. These are inferred "
            "explanations, not observed facts.",
            "items": [
                f"Conflict {h['conflict_id']}: \"{h['title']}\" (status={h['status']}, "
                f"support={h['support_score']:.2f}, origin={h['kind']})"
                for h in ctx["hypothesis_out"]
            ],
        }
    )
    sections.append(
        {
            "heading": "Hypothesis Ranking",
            "body": "Competing hypotheses are ranked by documented evidence weight. Scores are "
            "bounded support indicators, not calibrated probabilities.",
            "items": ranking_items,
        }
    )

    # legacy evidence-by-hypothesis sections
    sections.append(
        {
            "heading": "Evidence Supporting Each Hypothesis",
            "body": "",
            "items": [
                f"Evidence {e['id']} supports hypothesis {e['supports_hypothesis_id']}: {e['description']}"
                for e in ctx["evidence_out"]
                if e["supports_hypothesis_id"]
            ],
        }
    )
    sections.append(
        {
            "heading": "Evidence Contradicting Each Hypothesis",
            "body": "",
            "items": [
                f"Evidence {e['id']} contradicts hypothesis {e['contradicts_hypothesis_id']}: {e['description']}"
                for e in ctx["evidence_out"]
                if e["contradicts_hypothesis_id"]
            ],
        }
    )

    # 9. verification
    sections.append(
        {
            "heading": "Verification Results",
            "body": "Reliability/relevance are bounded quality indicators; 'unverified' means no "
            "verification step has been recorded.",
            "items": [
                f"Evidence {v['evidence_id']} [{v['evidence_type']}] verification={v['verification_status']} "
                f"(reliability={v['reliability_score']:.2f}, relevance={v['relevance_score']:.2f}, "
                f"weight={v['weight']:.2f})"
                for v in verification_out
            ]
            or ["No evidence was available to verify."],
        }
    )

    # 10. conclusion / inconclusive
    sections.append(
        {
            "heading": "Final Conclusion or Inconclusive Status",
            "body": "Each conclusion is the system's adjudication for a recorded conflict."
            + (
                " No definitive conclusion was produced; the investigation is inconclusive."
                if all(c["is_inconclusive"] for c in ctx["conclusion_out"]) and ctx["conclusion_out"]
                else ""
            ),
            "items": [
                f"Conflict {c['conflict_id']} -> {c['decision_type']} (confidence {c['confidence']:.2f}): {c['conclusion']}"
                for c in ctx["conclusion_out"]
            ]
            or ["No conclusion could be produced."],
        }
    )

    # 11. confidence interpretation
    sections.append(
        {
            "heading": "Confidence and its Limitations",
            "body": f"Overall confidence (mean of conclusions): {confidence:.2f}. "
            + CONFIDENCE_INTERPRETATION,
            "items": limitations,
        }
    )

    # 12. missing evidence / unresolved
    sections.append({"heading": "Unresolved Questions", "body": "", "items": unresolved or ["None recorded."]})
    sections.append(
        {
            "heading": "Evidence Gaps and Uncertainty",
            "body": "Missing evidence that limits confidence in any conclusion."
            if evidence_gaps
            else "No explicit evidence gaps were recorded."
            if conflicts
            else "",
            "items": evidence_gaps,
        }
    )

    # 13. human review status
    sections.append(
        {
            "heading": "Human Review Status",
            "body": f"Status: {human_review_status['status']} "
            f"({human_review_status['decisions_recorded']} decision(s) recorded).",
            "items": [
                f"Conflict {cid} is awaiting human review."
                for cid in human_review_status["conflicts_awaiting_review"]
            ]
            or ["No conflict is currently awaiting human review."],
        }
    )
    sections.append(
        {
            "heading": "Recommended Next Steps",
            "body": "",
            "items": ctx["recommendations"],
        }
    )
    sections.append(
        {
            "heading": "Human Review Notes",
            "body": "This report was produced by an automated evidence-driven system. "
            "It supports, but does not replace, professional judgement.",
            "items": [f"Conflict {c['id']} requires human review." for c in conflict_out if c["status"] == "human_review"],
        }
    )
    sections.append(
        {
            "heading": "Human Review Decisions",
            "body": "Recorded human decisions on this investigation's conclusions.",
            "items": [
                f"Conclusion {r['conclusion_id']} ({r['previous_decision_type']}) -> {r['decision']} "
                f"by {r['reviewer']}" + (f": {r['note']}" if r["note"] else "")
                for r in ctx["review_out"]
            ]
            or ["No human review decisions have been recorded yet."],
        }
    )

    # 14. agent activity summary
    summary = activity_summary
    sections.append(
        {
            "heading": "Agent Activity Summary",
            "body": f"{summary['count']} agent action(s) were recorded.",
            "items": [
                f"{a['agent_name']}: {a['actions']} action(s), {a['successes']} success, "
                f"{a['failures']} failed, {a['total_duration_ms']} ms total"
                for a in summary["by_agent"]
            ]
            or ["No agent activity was recorded."],
        }
    )

    # 15. limitations, timestamps and audit trail
    sections.append(
        {
            "heading": "Limitations and Timestamps",
            "body": "All times are UTC. Confidence is a bounded support indicator, not a probability.",
            "items": [
                f"Created: {timestamps['created_at'] or '—'}",
                f"Started: {timestamps['started_at'] or '—'}",
                f"Completed: {timestamps['completed_at'] or '—'}",
                f"Report generated: {timestamps['generated_at'] or '—'}",
                f"Duration: {timestamps['duration_seconds']} second(s)"
                if timestamps["duration_seconds"] is not None
                else "Duration: not recorded",
            ]
            + [f"Limitation: {l}" for l in limitations],
        }
    )

    # stop reason (legacy heading preserved)
    sections.append(
        {
            "heading": "Investigation Stopping Reason",
            "body": STOP_REASON_TEXT.get(
                investigation.stop_reason, safe_text(investigation.stop_reason) or "Not recorded."
            ),
            "items": [],
        }
    )

    # audit trail
    sections.append(
        {
            "heading": "Audit Trail",
            "body": "Every recorded blackboard change for this investigation, newest last.",
            "items": [
                f"#{a['id']} {a['created_at'] or '—'} [{a['entity_type']} {a['entity_id']}] "
                f"{a['action']} by {a['actor']}: {a['summary']}"
                for a in reversed(ctx["audit_events"])
            ]
            or ["No audit entries were recorded."],
        }
    )

    # data-quality warnings
    if warnings:
        sections.append(
            {
                "heading": "Report Warnings",
                "body": "Data-completeness notices that affect how this report should be read.",
                "items": warnings,
            }
        )

    return sections


def _to_markdown(investigation: Investigation, sections: list[dict]) -> str:
    lines = [f"# Investigation Report: {escape_text(investigation.name)}", ""]
    lines.append(f"*Generated: {datetime.now(timezone.utc).isoformat()}*")
    lines.append("")
    for section in sections:
        lines.append(f"## {escape_text(section['heading'])}")
        if section.get("body"):
            lines.append(escape_text(section["body"]))
            lines.append("")
        for item in section.get("items", []):
            lines.append(f"- {escape_text(item)}")
        lines.append("")
    return "\n".join(lines)
