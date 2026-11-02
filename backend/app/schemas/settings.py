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


class LLMSettingsOut(BaseModel):
    configured: bool
    active: bool
    source: str
    key_hint: str | None = None
    model: str | None = None
    base_url: str | None = None
    provider: str
    enable_llm: bool
    reasoning_mode: str
    effective_mode: str
    storage: str
    note: str


class LLMSettingsUpdate(BaseModel):
    """Provider credentials. ``api_key`` is never echoed back by the API."""

    api_key: str = Field(default="", max_length=512)
    model: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    enable_llm: bool = True
