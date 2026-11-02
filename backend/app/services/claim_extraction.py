"""Deterministic, rule-based claim extraction.

This module is intentionally independent of the LLM service. It parses
sentences into structured claims (measurements, states, events, statements),
preserving source provenance. It never invents content: a claim is only
produced from text that is actually present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

UNIT_ALIASES = {
    "°c": "°C", "c": "°C", "degrees": "°C", "degree celsius": "°C",
    "degree c": "°C", "celsius": "°C",
    "°f": "°F", "f": "°F", "fahrenheit": "°F",
    "mm/s": "mm/s", "mm": "mm", "rpm": "rpm",
    "hz": "Hz", "khz": "kHz", "kpa": "kPa", "bar": "bar", "psi": "psi",
    "%": "%", "kg": "kg", "l/min": "L/min",
}

_MEASUREMENT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(°?\s?[cCfF]\b|degrees?\b|mm/s|mm\b|rpm\b|kHz\b|Hz\b|kPa\b|bar\b|psi\b|%|kg\b|L/min\b)",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

SUBJECT_KEYWORDS = [
    "temperature", "vibration", "pressure", "speed", "rpm", "current", "voltage",
    "noise", "humidity", "flow", "level", "calibration", "sensor", "machine",
    "output", "load", "torque",
]
STATE_VERBS = ["observed", "detected", "present", "recorded", "reported", "measured", "noted", "found"]
NEGATIONS = ["no ", "not ", "without ", "none", "never", "did not", "wasn't", "was not", "weren't"]

_TIME_WORDS = {"morning": 9, "noon": 12, "afternoon": 15, "evening": 18, "night": 21}


@dataclass
class ExtractedClaim:
    claim_text: str
    subject: str
    predicate: str
    object_value: str
    numeric_value: float | None = None
    unit: str = ""
    polarity: str = "affirmative"
    claim_type: str = "statement"
    timestamp_value: datetime | None = None
    confidence: float = 0.6
    meta: dict = field(default_factory=dict)


def normalize_unit(unit: str) -> str:
    key = unit.strip().lower().replace(" ", "")
    if key in UNIT_ALIASES:
        return UNIT_ALIASES[key]
    low = unit.strip().lower()
    return UNIT_ALIASES.get(low, unit.strip())


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _find_subject(sentence_lower: str) -> str:
    for kw in SUBJECT_KEYWORDS:
        if kw in sentence_lower:
            return kw
    return ""


def _parse_date(sentence: str) -> datetime | None:
    m = _DATE_RE.search(sentence)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_time(sentence: str) -> datetime | None:
    date = _parse_date(sentence)
    m = _TIME_RE.search(sentence)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            if date is not None:
                return date.replace(hour=h, minute=mi)
            # Store time only on a neutral date so ordering by time works.
            return datetime(2000, 1, 1, h, mi)
    low = sentence.lower()
    for word, hour in _TIME_WORDS.items():
        if word in low:
            if date is not None:
                return date.replace(hour=hour, minute=0)
            return datetime(2000, 1, 1, hour, 0)
    return date


def _is_negated(sentence_lower: str) -> bool:
    return any(neg in sentence_lower for neg in NEGATIONS)


def extract_claims(text: str, source_reference: str = "") -> list[ExtractedClaim]:
    """Extract structured claims from a block of text."""
    claims: list[ExtractedClaim] = []
    for sentence in split_sentences(text):
        low = sentence.lower()
        subject = _find_subject(low)
        ts = _parse_time(sentence)
        negated = _is_negated(low)

        measurements = list(_MEASUREMENT_RE.finditer(sentence))
        if measurements:
            for match in measurements:
                value = float(match.group(1))
                unit = normalize_unit(match.group(2))
                subj = subject or _subject_from_measurement(sentence, match.start()) or "value"
                claims.append(
                    ExtractedClaim(
                        claim_text=sentence,
                        subject=subj,
                        predicate="measured_value",
                        object_value=match.group(0).strip(),
                        numeric_value=value,
                        unit=unit,
                        polarity="negative" if negated else "affirmative",
                        claim_type="measurement",
                        timestamp_value=ts,
                        confidence=0.72,
                        meta={"source_reference": source_reference},
                    )
                )
            # Also capture a state aspect in the same sentence if a state verb exists.
            if subject and any(v in low for v in STATE_VERBS) and not measurements_of_subject(measurements, subject):
                pass
            continue

        # State / event claims.
        if subject and any(v in low for v in STATE_VERBS):
            claims.append(
                ExtractedClaim(
                    claim_text=sentence,
                    subject=subject,
                    predicate="state_observed",
                    object_value="absent" if negated else "present",
                    polarity="negative" if negated else "affirmative",
                    claim_type="state",
                    timestamp_value=ts,
                    confidence=0.6,
                    meta={"source_reference": source_reference},
                )
            )
        elif subject and any(w in low for w in ["normal", "abnormal", "operating", "calibrat"]):
            claims.append(
                ExtractedClaim(
                    claim_text=sentence,
                    subject=subject,
                    predicate="status",
                    object_value="abnormal" if "abnormal" in low else ("calibration" if "calibrat" in low else "normal"),
                    polarity="negative" if negated else "affirmative",
                    claim_type="state",
                    timestamp_value=ts,
                    confidence=0.5,
                    meta={"source_reference": source_reference},
                )
            )
    return claims


def measurements_of_subject(measurements, subject: str) -> bool:  # pragma: no cover - helper
    return bool(measurements) and bool(subject)


def _subject_from_measurement(sentence: str, pos: int) -> str:
    prefix = sentence[:pos].strip()
    words = re.findall(r"[A-Za-z]+", prefix)
    if not words:
        return ""
    return words[-1].lower()


def extract_observations(text: str, source_reference: str = "") -> list[dict]:
    """Return raw observations (one per sentence) with provenance."""
    out = []
    for sentence in split_sentences(text):
        out.append(
            {
                "text": sentence,
                "observation_type": "statement",
                "source_reference": source_reference,
            }
        )
    return out
