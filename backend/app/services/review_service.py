"""Human-in-the-loop review service.

Records an explicit, attributed human decision on a conclusion and moves the
corresponding conflict to the status implied by that decision. Every review is
written to the audit trail and announced on the event stream so the UI and the
live workflow stay in sync.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..blackboard.events import event_bus
from ..models import Conclusion, Conflict, HumanReview, enums
from . import audit_service

# Human decision -> resulting conflict status.
class ReviewError(ValueError):
    """Raised when a review cannot be recorded."""


_DECISION_TO_STATUS = {
    enums.ReviewDecision.APPROVED.value: "resolved",
    enums.ReviewDecision.REJECTED.value: "open",
    enums.ReviewDecision.INCONCLUSIVE.value: "inconclusive",
    enums.ReviewDecision.REQUEST_MORE_INVESTIGATION.value: "human_review",
    enums.ReviewDecision.REOPENED.value: "open",
}

_DECISION_MESSAGE = {
    enums.ReviewDecision.APPROVED.value: "Conclusion approved; conflict marked resolved.",
    enums.ReviewDecision.REJECTED.value: "Conclusion rejected; conflict reopened for further work.",
    enums.ReviewDecision.INCONCLUSIVE.value: "Conclusion marked inconclusive; conflict status set to inconclusive.",
    enums.ReviewDecision.REQUEST_MORE_INVESTIGATION.value: "More investigation requested; conflict remains under human review.",
    enums.ReviewDecision.REOPENED.value: "Previously reviewed finding reopened for fresh investigation.",
}


def submit_review(
    db: Session,
    *,
    conclusion_id: int,
    decision: str,
    reviewer: str = "human reviewer",
    note: str = "",
) -> dict:
    conclusion = db.get(Conclusion, conclusion_id)
    if conclusion is None:
        raise ReviewError("Conclusion not found.")
    if decision not in _DECISION_TO_STATUS:
        raise ReviewError(
            f"Invalid decision '{decision}'. Allowed: {sorted(_DECISION_TO_STATUS)}"
        )

    conflict = db.get(Conflict, conclusion.conflict_id) if conclusion.conflict_id else None
    previous = conclusion.decision_type

    review = HumanReview(
        conclusion_id=conclusion.id,
        conflict_id=conclusion.conflict_id,
        investigation_id=conclusion.investigation_id,
        decision=decision,
        reviewer=reviewer or "human reviewer",
        note=note or "",
        previous_decision_type=previous,
    )
    db.add(review)
    db.flush()

    new_status = _DECISION_TO_STATUS[decision]
    if conflict is not None:
        conflict.status = new_status

    audit_service.record(
        db,
        entity_type="human_review",
        entity_id=review.id,
        action="submitted",
        actor=reviewer or "human reviewer",
        investigation_id=conclusion.investigation_id,
        conflict_id=conclusion.conflict_id,
        summary=(
            f"Human review of conclusion {conclusion.id}: {decision} "
            f"(conflict -> {new_status})."
        ),
        detail={
            "decision": decision,
            "note": note or "",
            "conclusion_id": conclusion.id,
            "previous_decision_type": previous,
            "resulting_conflict_status": new_status,
        },
    )
    db.commit()
    db.refresh(review)

    event_bus.publish(
        db,
        conclusion.investigation_id,
        enums.EventType.HUMAN_REVIEW_RECORDED.value,
        {
            "review_id": review.id,
            "conclusion_id": conclusion.id,
            "conflict_id": conclusion.conflict_id,
            "decision": decision,
            "reviewer": review.reviewer,
            "conflict_status": new_status,
            "previous_decision_type": previous,
        },
    )

    return {
        "review": review,
        "conflict_status": new_status,
        "conclusion_decision_type": conclusion.decision_type,
        "message": _DECISION_MESSAGE[decision],
    }


def _reviews_stmt(
    *,
    conclusion_id: int | None,
    conflict_id: int | None,
    investigation_id: int | None,
):
    stmt = select(HumanReview).order_by(HumanReview.created_at.desc(), HumanReview.id.desc())
    if conclusion_id is not None:
        stmt = stmt.where(HumanReview.conclusion_id == conclusion_id)
    if conflict_id is not None:
        stmt = stmt.where(HumanReview.conflict_id == conflict_id)
    if investigation_id is not None:
        stmt = stmt.where(HumanReview.investigation_id == investigation_id)
    return stmt


def count_reviews(
    db: Session,
    *,
    conclusion_id: int | None = None,
    conflict_id: int | None = None,
    investigation_id: int | None = None,
) -> int:
    from sqlalchemy import func

    stmt = _reviews_stmt(
        conclusion_id=conclusion_id,
        conflict_id=conflict_id,
        investigation_id=investigation_id,
    )
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    return int(db.execute(count_stmt).scalar() or 0)


def list_reviews(
    db: Session,
    *,
    conclusion_id: int | None = None,
    conflict_id: int | None = None,
    investigation_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[HumanReview]:
    stmt = _reviews_stmt(
        conclusion_id=conclusion_id,
        conflict_id=conflict_id,
        investigation_id=investigation_id,
    )
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())
