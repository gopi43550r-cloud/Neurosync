"""Health and configuration status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services import settings_service

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict:
    """Liveness probe: process is up. Deliberately does not touch the database
    so a transient DB issue does not cause an orchestrator to kill the
    container."""
    return {"status": "ok"}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    effective = settings_service.effective_mode(db)
    active = effective == settings_service.MODE_AI
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "ai_configured": settings.llm_configured,
        "mode": "ai" if active else "demonstration",
        "reasoning_mode": settings_service.get_reasoning_mode(db),
        "effective_mode": effective,
        "llm_model": settings.openai_model if settings.llm_configured else None,
    }


@router.get("/config")
def config_info() -> dict:
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "mode": "ai" if settings.llm_configured else "demonstration",
        "ai_configured": settings.llm_configured,
        "max_upload_mb": settings.max_upload_mb,
        "scheduler_weights": settings.weights,
        "default_iteration_limit": settings.default_iteration_limit,
        "default_min_evidence": settings.default_min_evidence,
        "agent_max_retries": settings.agent_max_retries,
        "max_agent_executions": settings.max_agent_executions,
        "max_attempts_per_action": settings.max_attempts_per_action,
    }
