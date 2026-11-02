"""Investigation chat endpoints.

The assistant reads only the investigation's own stored rows. It never calls an
external model, so it cannot answer with unsupported prose; when the data cannot
answer a question the response says so explicitly.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Investigation
from ..schemas.chat import ChatAnswerOut, ChatRequest, ChatSuggestionsOut
from ..services.chat_assistant_service import (
    answer_question,
    build_context,
    suggestions_for,
)

router = APIRouter(tags=["chat"])


def _get_investigation(db: Session, investigation_id: int) -> Investigation:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return investigation


@router.post("/investigations/{investigation_id}/chat", response_model=ChatAnswerOut)
def ask_investigation(
    investigation_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatAnswerOut:
    investigation = _get_investigation(db, investigation_id)
    result = answer_question(
        db,
        investigation,
        payload.question,
        conflict_id=payload.conflict_id,
        claim_id=payload.claim_id,
        hypothesis_id=payload.hypothesis_id,
        document_id=payload.document_id,
    )
    return ChatAnswerOut(**result)


@router.get(
    "/investigations/{investigation_id}/chat/suggestions",
    response_model=ChatSuggestionsOut,
)
def chat_suggestions(
    investigation_id: int,
    db: Session = Depends(get_db),
) -> ChatSuggestionsOut:
    investigation = _get_investigation(db, investigation_id)
    context = build_context(db, investigation)
    return ChatSuggestionsOut(
        investigation_id=investigation.id,
        investigation_name=investigation.name,
        suggestions=suggestions_for(investigation, context),
        note=(
            "Suggestions are generated from the investigation's current records. "
            "Every answer cites the stored record it came from."
        ),
    )
