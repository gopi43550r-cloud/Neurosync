"""Schemas for runtime reasoning-mode configuration."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReasoningSettingsOut(BaseModel):
    reasoning_mode: str
    effective_mode: str
    llm_configured: bool
    model: str | None = None
    provider: str | None = None
    available_modes: list[str] = []
    note: str = ""


class ReasoningModeUpdate(BaseModel):
    mode: str = Field(min_length=1, max_length=40)
