"""Client-facing redaction of event payloads.

Progress events streamed to the browser (and the recent-events list) must never
expose raw document or claim text. An event's identifiers and structured
metadata are preserved so the UI can still show *what* happened and *which*
records were involved, while free-text document content is removed and listed in
``redacted_fields`` so the omission is explicit rather than silent.

Redaction happens only at the serialization boundary. The persisted event log
keeps the full payload, so the audit trail and traceability services remain
complete.
"""
from __future__ import annotations

from typing import Any

# Payload keys that carry raw document / claim content and must never be sent to
# a client as part of a progress event.
SENSITIVE_KEYS = frozenset(
    {
        "claim_text",
        "text",
        "content",
        "document_text",
        "document_content",
        "source_text",
        "text_preview",
        "observation_text",
        "excerpt",
        "quote",
        "evidence_quote",
        "raw",
        "body",
    }
)

# Any other free-text value longer than this is treated as content and truncated.
MAX_FREE_TEXT = 400


def redact_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``payload`` with document content removed."""
    if not isinstance(payload, dict):
        return {}
    redacted: list[str] = []

    def walk(value: Any, key: str | None) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k in SENSITIVE_KEYS and v not in (None, ""):
                    redacted.append(k)
                    continue
                out[k] = walk(v, k)
            return out
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and len(value) > MAX_FREE_TEXT:
            redacted.append(key or "text")
            return value[:MAX_FREE_TEXT] + "…"
        return value

    result = walk(payload, None)
    if redacted:
        unique: list[str] = []
        for field in redacted:
            if field not in unique:
                unique.append(field)
        result["redacted_fields"] = unique
    return result
