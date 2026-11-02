"""Runtime settings endpoints.

The reasoning mode is the user-selectable switch between fully deterministic
reasoning and AI-assisted reasoning. The effective mode reported here accounts
for whether an LLM provider is actually configured, so the UI can explain any
degradation instead of silently ignoring the preference.

The ``/llm`` endpoints manage the optional OpenAI-compatible API key from the
Settings page. They never return the key itself: only a boolean, a masked hint
and the non-secret provider settings.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..schemas.settings import (
    LLMSettingsOut,
    LLMSettingsUpdate,
    ReasoningModeUpdate,
    ReasoningSettingsOut,
)
from ..services import llm_settings_service, settings_service
from ..services.llm_settings_service import LLMSettingsError
from ..services.settings_service import SettingsError

router = APIRouter(prefix="/settings", tags=["settings"])


def _require_key_management_allowed() -> None:
    """Refuse anonymous credential writes on a production instance.

    In production the API is expected to sit behind an authenticating reverse
    proxy (``API_TOKEN``). Without that gate, an endpoint that can replace the
    provider credentials must not be exposed.
    """
    if settings.is_production and not settings.api_token:
        raise HTTPException(
            status_code=403,
            detail=(
                "API-key management is disabled on an unauthenticated production "
                "instance. Set API_TOKEN (or inject the key via the environment) "
                "before using this endpoint."
            ),
        )


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


@router.get("/llm", response_model=LLMSettingsOut)
def get_llm_settings(db: Session = Depends(get_db)) -> LLMSettingsOut:
    """Provider status without ever exposing the key."""
    return LLMSettingsOut(**llm_settings_service.describe(db))


@router.put("/llm", response_model=LLMSettingsOut)
def update_llm_settings(
    payload: LLMSettingsUpdate, db: Session = Depends(get_db)
) -> LLMSettingsOut:
    """Save the API key (or update model/base URL) and apply it immediately."""
    _require_key_management_allowed()
    try:
        described = llm_settings_service.save(
            db,
            api_key=payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
            enable_llm=payload.enable_llm,
        )
    except LLMSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LLMSettingsOut(**described)


@router.delete("/llm/key", response_model=LLMSettingsOut)
def delete_llm_key(db: Session = Depends(get_db)) -> LLMSettingsOut:
    """Remove the managed key. Environment-provided keys return after restart."""
    _require_key_management_allowed()
    return LLMSettingsOut(**llm_settings_service.clear(db))
