"""Structured, secret-safe logging configuration.

Two output formats are supported, selected by ``LOG_FORMAT``:

* ``text`` (default) - human-readable single-line records for local development.
* ``json`` - one JSON object per line, suitable for log aggregation platforms.

Regardless of format, a redaction filter removes any configured secret value
(the API bearer token and the LLM API key) from every record before it is
emitted, so credentials can never leak into logs even if a caller accidentally
formats one into a message.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

REDACTED = "***REDACTED***"


class RedactionFilter(logging.Filter):
    """Scrubs configured secret strings from log records."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        # Longest first so a secret that contains another is redacted whole.
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = message
        for secret in self._secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, REDACTED)
        if redacted != message:
            # Collapse to a fully-formatted message so the raw secret in
            # record.args cannot be re-expanded downstream.
            record.msg = redacted
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal, dependency-free JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_format: bool = False, secrets: list[str] | None = None) -> None:
    """Install a single stream handler on the root logger.

    Idempotent enough for repeated calls: existing handlers are replaced so the
    application never emits duplicate lines.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_format
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(RedactionFilter(secrets or []))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.strip().upper(), logging.INFO))

    # Uvicorn installs its own handlers; let its records flow through ours
    # instead of being duplicated or dropped.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True
