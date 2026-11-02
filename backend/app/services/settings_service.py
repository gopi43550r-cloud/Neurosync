"""Runtime reasoning-mode setting.

The reasoning mode is the user-selectable master switch for LLM assistance.
It is persisted in the ``app_settings`` table (default: deterministic) so it
survives restarts and can be changed from the Settings UI without editing code.

Two distinct concepts are tracked:

* ``reasoning_mode`` - the *preference* the user selected ("deterministic" or
  "ai_assisted"). This is what the Settings UI shows.
* ``effective_mode`` - the mode actually in force. If the user requests AI
  assistance but no provider is configured (no API key, or LLM disabled in the
  environment), the effective mode degrades to deterministic. The API reports a
  human-readable note explaining any degradation, so a preference is never
  silently ignored.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AppSetting

REASONING_MODE_KEY = "reasoning_mode"
MODE_DETERMINISTIC = "deterministic"
MODE_AI = "ai_assisted"
VALID_MODES = (MODE_DETERMINISTIC, MODE_AI)


class SettingsError(ValueError):
    """Raised when a setting value is invalid."""


def get_reasoning_mode(db: Session) -> str:
    """Return the stored preference (never raises; defaults to deterministic)."""
    row = db.get(AppSetting, REASONING_MODE_KEY)
    if row is None or row.value not in VALID_MODES:
        return MODE_DETERMINISTIC
    return row.value


def set_reasoning_mode(db: Session, mode: str) -> str:
    if mode not in VALID_MODES:
        raise SettingsError(f"Invalid reasoning mode '{mode}'. Allowed: {list(VALID_MODES)}.")
    row = db.get(AppSetting, REASONING_MODE_KEY)
    if row is None:
        row = AppSetting(key=REASONING_MODE_KEY, value=mode)
        db.add(row)
    else:
        row.value = mode
    db.commit()
    return mode


def llm_available() -> bool:
    """True when a provider is configured in the environment (key + enabled)."""
    return settings.llm_configured


def effective_mode(db: Session) -> str:
    """The mode actually in force, accounting for provider availability."""
    if get_reasoning_mode(db) == MODE_AI and llm_available():
        return MODE_AI
    return MODE_DETERMINISTIC


def llm_enabled(db: Session) -> bool:
    """True when a run in this process should call the LLM provider."""
    return effective_mode(db) == MODE_AI


def describe(db: Session) -> dict:
    """A serialisable summary of the reasoning configuration and its state."""
    preference = get_reasoning_mode(db)
    effective = effective_mode(db)
    available = llm_available()
    if preference == MODE_AI and not available:
        note = (
            "AI assistance was selected but no provider is configured. "
            "Set OPENAI_API_KEY and ENABLE_LLM=true in the backend environment "
            "to activate it. Running deterministic reasoning meanwhile."
        )
    elif preference == MODE_AI:
        note = "AI assistance is active; results are validated against the documents."
    else:
        note = (
            "Deterministic reasoning is active. Every result is reproducible from "
            "the document text and the transparent scoring rules."
        )
    return {
        "reasoning_mode": preference,
        "effective_mode": effective,
        "llm_configured": available,
        "model": settings.openai_model if available else None,
        "provider": settings.llm_provider if available else None,
        "available_modes": list(VALID_MODES),
        "note": note,
    }
