"""Runtime management of the optional OpenAI-compatible API key.

The application is fully functional without a key. This module adds a small,
server-side way to add or remove one from the Settings page so operators do not
have to edit files by hand.

Design rules:

* The key is **never returned** by the API. Responses only expose a boolean and,
  when a key exists, a masked hint (last four characters).
* The key is persisted to ``backend/.env.local`` (git-ignored) with restrictive
  permissions where the OS supports them. Real process environment variables
  still take precedence on restart.
* Values written to the env file are strictly validated so a key or URL can never
  inject additional environment lines.
* Management writes are blocked on an unauthenticated production instance (see
  the API layer), because anyone able to reach the endpoint would otherwise be
  able to replace the provider credentials.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, settings
from . import settings_service

MANAGED_KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "ENABLE_LLM")
DEFAULT_ENV_FILE = BACKEND_DIR / ".env.local"

# Provider keys are URL-safe in practice. Restricting the alphabet (a) rejects
# newline/quote injection into the dotenv file and (b) keeps the value safe to
# write unquoted.
_API_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=\-:]{8,512}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,120}$")


class LLMSettingsError(ValueError):
    """Raised when an API key or provider setting is invalid."""


def env_file_path() -> Path:
    """Location of the managed env file (overridable for tests/deployments)."""
    override = os.environ.get("NEUROSYNC_LLM_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_ENV_FILE


def _storage_label() -> str:
    path = env_file_path()
    try:
        return str(path.relative_to(BACKEND_DIR))
    except ValueError:
        return str(path)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw = stripped.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        if name not in MANAGED_KEYS:
            continue
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _source() -> str:
    """Where the key in force came from."""
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "environment"
    if _read_env_file(env_file_path()).get("OPENAI_API_KEY", "").strip():
        return "saved"
    if settings.openai_api_key:
        # Loaded from backend/.env (or injected without appearing in os.environ,
        # e.g. a container secret).
        return "environment"
    return "none"


def _hint(key: str) -> str:
    if len(key) < 8:
        return "\u2022\u2022\u2022\u2022"
    return "\u2022\u2022\u2022\u2022" + key[-4:]


def _validate_api_key(raw: str) -> str:
    key = (raw or "").strip()
    if not key:
        raise LLMSettingsError("An API key is required.")
    if not _API_KEY_RE.fullmatch(key):
        raise LLMSettingsError(
            "The API key contains unsupported characters or is outside the "
            "8-512 character range."
        )
    return key


def _validate_model(raw: str) -> str:
    value = (raw or "").strip()
    if not _MODEL_RE.fullmatch(value):
        raise LLMSettingsError(
            "Model names may contain letters, digits, '.', '_', ':', '/' and '-' "
            "(1-120 characters)."
        )
    return value


def _validate_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value or len(value) > 500 or any(ch.isspace() for ch in value):
        raise LLMSettingsError("Enter a valid http(s) base URL.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMSettingsError("The base URL must start with http:// or https://.")
    if parsed.username or parsed.password:
        raise LLMSettingsError("Credentials must not be embedded in the base URL.")
    if parsed.query or parsed.fragment:
        raise LLMSettingsError("The base URL must not contain a query string or fragment.")
    return value.rstrip("/")


def _write_env_file(values: dict[str, str]) -> None:
    """Atomically update managed keys, preserving unrelated lines/comments."""
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    rendered: list[str] = []
    seen: set[str] = set()
    for line in existing.splitlines():
        stripped = line.strip()
        name = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name.startswith("export "):
                name = name[len("export ") :].strip()
        if name in values:
            if name not in seen:
                rendered.append(f"{name}={values[name]}")
                seen.add(name)
            continue
        rendered.append(line)

    for name in MANAGED_KEYS:
        if name in values and name not in seen:
            rendered.append(f"{name}={values[name]}")
            seen.add(name)

    text = "\n".join(rendered).rstrip("\n") + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".env.local.", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:  # Windows only honours the write bit; best effort.
            pass
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def describe(db: Session) -> dict:
    """Serialisable status. Never includes the key itself."""
    configured = bool(settings.openai_api_key)
    source = _source()
    reasoning_mode = settings_service.get_reasoning_mode(db)
    effective = settings_service.effective_mode(db)

    if not configured:
        note = (
            "No OpenAI API key is configured. Add one here, or set "
            "OPENAI_API_KEY in backend/.env. The app remains fully functional "
            "in deterministic mode without a key."
        )
    elif not settings.enable_llm:
        note = (
            "A key is configured but LLM assistance is disabled globally "
            "(ENABLE_LLM=false). Saving a key here enables it."
        )
    elif reasoning_mode != settings_service.MODE_AI:
        note = (
            "A key is configured. Select AI-assisted reasoning to use it; "
            "results are still validated against the documents."
        )
    else:
        note = "AI assistance is active; model output is validated against the documents."

    if source == "environment" and configured:
        note += (
            " The current key comes from the process environment or backend/.env; "
            "that value takes precedence over a key saved here after a restart."
        )

    return {
        "configured": configured,
        "active": settings.llm_configured,
        "source": source,
        "key_hint": _hint(settings.openai_api_key) if configured else None,
        "model": settings.openai_model,
        "base_url": settings.openai_base_url,
        "provider": settings.llm_provider,
        "enable_llm": settings.enable_llm,
        "reasoning_mode": reasoning_mode,
        "effective_mode": effective,
        "storage": _storage_label(),
        "note": note,
    }


def save(
    db: Session,
    *,
    api_key: str = "",
    model: str | None = None,
    base_url: str | None = None,
    enable_llm: bool = True,
) -> dict:
    """Save the key (or update provider settings) and apply it immediately."""
    supplied = (api_key or "").strip()
    if supplied:
        key = _validate_api_key(supplied)
    elif settings.openai_api_key:
        key = settings.openai_api_key
    else:
        raise LLMSettingsError(
            "An API key is required the first time you configure the provider."
        )

    resolved_model = _validate_model(model) if model else settings.openai_model
    resolved_base = (
        _validate_base_url(base_url) if base_url else settings.openai_base_url
    )

    _write_env_file(
        {
            "OPENAI_API_KEY": key,
            "OPENAI_MODEL": resolved_model,
            "OPENAI_BASE_URL": resolved_base,
            "ENABLE_LLM": "true" if enable_llm else "false",
        }
    )

    # Apply in-process so the change takes effect without a restart. Other
    # worker processes read the env file on their next start.
    settings.openai_api_key = key
    settings.openai_model = resolved_model
    settings.openai_base_url = resolved_base
    settings.enable_llm = enable_llm
    return describe(db)


def clear(db: Session) -> dict:
    """Remove the managed key (environment-provided keys return on restart)."""
    _write_env_file({"OPENAI_API_KEY": ""})
    settings.openai_api_key = ""
    settings.enable_llm = False
    return describe(db)
