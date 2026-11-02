"""Application configuration loaded from environment variables.

Secrets are never hardcoded. The application runs in a deterministic
demonstration mode when no LLM credentials are configured.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "NeuroSync"
    app_version: str = "1.0.0"
    database_url: str = "sqlite:///./neurosync.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_allow_credentials: bool = True
    max_upload_mb: int = 25
    # Upper bound on extracted document text (chars). Guards against
    # decompression/zip-bomb PDFs that expand far beyond the upload limit.
    max_extracted_chars: int = 5_000_000
    # Optional bearer token for all /api routes. Empty (default) disables
    # authentication for local, loopback-only deployments. Set a strong value
    # whenever the API is reachable beyond 127.0.0.1 and put it in the
    # environment (never in code or the frontend bundle).
    api_token: str = ""

    # Deployment / operations
    # "development" keeps local conveniences (docs enabled, verbose defaults).
    # Set to "production" for a hardened deployment (see docs/deployment.md).
    environment: str = "development"
    # Absolute or relative directory where uploaded files are stored. Leave
    # empty to use backend/uploads (local development). In production point this
    # at a persistent volume, e.g. /app/data/uploads.
    upload_dir: str = ""
    # Root log level (DEBUG/INFO/WARNING/ERROR) and format ("text" or "json").
    log_level: str = "INFO"
    log_format: str = "text"
    # Interactive API docs (/docs, /redoc, /openapi.json). Disable in production
    # to reduce surface area, or keep enabled if the API is access-restricted.
    enable_docs: bool = True
    # Comma-separated hostnames allowed by TrustedHostMiddleware. "*" (default)
    # disables host checking; set explicit hosts in production.
    trusted_hosts: str = "*"

    # Optional LLM integration
    llm_provider: str = "openai"  # provider identifier (OpenAI-compatible API)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2
    enable_llm: bool = False

    # Scheduler heuristic weights
    weight_severity: float = 0.30
    weight_uncertainty: float = 0.25
    weight_evidence_gap: float = 0.25
    weight_info_gain: float = 0.20

    # Investigation defaults
    default_iteration_limit: int = 25
    default_min_evidence: int = 1

    # Orchestration safeguards (see docs/orchestration.md)
    # Number of automatic retries for a failed agent execution (0 = no retry).
    agent_max_retries: int = 2
    # Hard ceiling on total agent executions per investigation, independent of
    # the iteration limit. Counts retries, so runaway processing is bounded even
    # if an agent keeps failing.
    max_agent_executions: int = 200
    # A single (agent, objective, conflict) action is skipped once it has been
    # executed this many times without any intervening blackboard change. This
    # is the anti-infinite-loop guard.
    max_attempts_per_action: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def json_logs(self) -> bool:
        return self.log_format.strip().lower() == "json"

    @property
    def secret_values(self) -> list[str]:
        """Values that must never appear in logs. Used by the log redactor."""
        return [v for v in (self.api_token, self.openai_api_key) if v]

    @property
    def llm_configured(self) -> bool:
        """True only when a key is present AND LLM assistance is enabled."""
        return bool(self.openai_api_key) and self.enable_llm

    @property
    def weights(self) -> dict[str, float]:
        total = (
            self.weight_severity
            + self.weight_uncertainty
            + self.weight_evidence_gap
            + self.weight_info_gain
        )
        total = total or 1.0
        return {
            "severity": self.weight_severity / total,
            "uncertainty": self.weight_uncertainty / total,
            "evidence_gap": self.weight_evidence_gap / total,
            "info_gain": self.weight_info_gain / total,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def _resolve_upload_dir() -> Path:
    """Storage location for uploaded files.

    Configurable via ``UPLOAD_DIR`` so a persistent volume can be mounted in
    production; defaults to ``backend/uploads`` for local development.
    """
    configured = settings.upload_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return BACKEND_DIR / "uploads"


UPLOAD_DIR = _resolve_upload_dir()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
