"""Runtime settings endpoints.

The reasoning mode is the user-selectable switch between fully deterministic
reasoning and AI-assisted reasoning. The effective mode reported here accounts
for whether an LLM provider is actually configured, so the UI can explain any
degradation instead of silently ignoring the preference.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.settings import ReasoningModeUpdate, ReasoningSettingsOut
from ..services import settings_service
from ..services.settings_service import SettingsError

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/reasoning", response_model=ReasoningSettingsOut)
def get_reasoning(db: Session = Depends(get_db)) -> ReasoningSettingsOut:
    return ReasoningSettingsOut(**settings_service.describe(db))


@router.put("/reasoning", response_model=ReasoningSettingsOut)
def update_reasoning(
    payload: ReasoningModeUpdate, db: Session = Depends(get_db)
) -> ReasoningSettingsOut:
    try:
        settings_service.set_reasoning_mode(db, payload.mode)
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReasoningSettingsOut(**settings_service.describe(db))
