"""Human-review schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import ORMModel

REVIEW_DECISIONS = {
    "approved",
    "rejected",
    "inconclusive",
    "request_more_investigation",
    "reopen",
}


class HumanReviewCreate(BaseModel):
    decision: str = Field(
        ...,
        description=(
            "approved | rejected | inconclusive | request_more_investigation | reopen"
        ),
    )
    reviewer: str = Field("human reviewer", max_length=200)
    note: str = Field("", max_length=2000)


class HumanReviewOut(ORMModel):
    id: int
    conclusion_id: int | None = None
    conflict_id: int | None = None
    investigation_id: int | None = None
    decision: str
    reviewer: str = ""
    note: str = ""
    previous_decision_type: str = ""
    review_kind: str = "local_manual_review"
    created_at: datetime | None = None


class ReviewResultOut(BaseModel):
    review: HumanReviewOut
    conflict_status: str
    conclusion_decision_type: str
    message: str = ""
