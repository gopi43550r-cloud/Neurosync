"""Schemas for the investigation chat assistant.

The assistant is deterministic: every answer is assembled from records that are
already stored in the investigation. Citations therefore always point at a real
record id and, where one exists, a source document with a page or character
location. ``insufficient_information`` is explicit rather than hidden.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class ChatRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    # Optional context supplied by the UI. When present these disambiguate
    # "this conflict" / "this claim" / "this hypothesis" without guessing.
    conflict_id: int | None = Field(default=None, ge=1)
    claim_id: int | None = Field(default=None, ge=1)
    hypothesis_id: int | None = Field(default=None, ge=1)
    document_id: int | None = Field(default=None, ge=1)


class ChatCitation(BaseModel):
    """One resolvable reference used in an answer."""

    number: int
    kind: str  # investigation | document | claim | conflict | evidence | hypothesis | conclusion
    record_id: int | None = None
    label: str = ""
    document_id: int | None = None
    document_filename: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    text_location: str = ""
    snippet: str = ""
    link: str | None = None


class ChatAnswerOut(BaseModel):
    investigation_id: int
    investigation_name: str
    question: str
    intent: str
    answer: str
    insufficient_information: bool = False
    missing_information: list[str] = []
    citations: list[ChatCitation] = []
    follow_up_questions: list[str] = []
    data_sources: dict[str, int] = {}
    methodology: str = ""
    caveat: str = ""
    analyzed_at: datetime


class ChatSuggestionsOut(BaseModel):
    investigation_id: int
    investigation_name: str
    suggestions: list[str] = []
    note: str = ""
