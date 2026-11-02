"""Evidence-grounded fact verification for extracted claims.

The verifier answers one question per claim: *do the documents and evidence that
actually exist in NeuroSync support it, contradict it, do both, or neither?*

Design rules
------------
* **Nothing is invented.** Every supporting, contradicting or contextual item is
  a real row (another ``Claim`` or a stored ``Evidence`` record) or a verbatim
  sentence sliced out of ``DocumentContent.text``. If no such item exists the
  claim is ``unverified``.
* **Independent corroboration is required for ``supported``.** A claim extracted
  from a document is not "supported" merely because its own source contains it.
  Only a different document (or user-supplied evidence) counts as independent.
* **Contradictions are only asserted on comparable facts.** Claims must share a
  subject and property. Measurements are compared after unit conversion with the
  same 2% tolerance used by the conflict detector. Readings separated by at least
  30 minutes are reported as contextual (possible genuine change), not as a
  contradiction.
* **The classifier is deterministic.** An optional LLM layer may rewrite the
  explanation, but it cannot change the verdict and every citation it returns is
  validated against the evidence actually shown. When no provider is configured
  the deterministic explanation is used unchanged.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Claim, Conflict, Document, DocumentContent, Evidence, Investigation
from ..models.enums import FactVerdict
from .claim_extraction import extract_claims, normalize_unit

MEASUREMENT_TOLERANCE = 0.02  # same 2% relative tolerance as the conflict detector
MIN_TEMPORAL_GAP_MINUTES = 30

_TEMP_CONVERTERS = {
    "°C": lambda v: v,
    "°F": lambda v: (v - 32.0) * 5.0 / 9.0,
    "K": lambda v: v - 273.15,
}

VERDICT_LABELS = {
    FactVerdict.SUPPORTED.value: "Supported",
    FactVerdict.CONTRADICTED.value: "Contradicted",
    FactVerdict.PARTIALLY_SUPPORTED.value: "Partially Supported",
    FactVerdict.UNVERIFIED.value: "Unverified",
}

METHODOLOGY = (
    "Each claim is compared with (a) other extracted claims and (b) verbatim "
    "sentences from other uploaded documents that share its subject and property. "
    "Measurements are compared after unit normalisation with a 2% tolerance; "
    "states are compared by polarity and value; timestamps prevent genuine change "
    "over time from being treated as a contradiction. A claim is Supported only "
    "when at least one independent source corroborates it and none contradicts it."
)

CAVEAT = (
    "This verdict is a deterministic, evidence-grounded comparison of the records "
    "stored in NeuroSync. It is not a calibrated probability and does not certify "
    "truth. Absence of evidence is reported as Unverified, never as false."
)

_STOPWORDS = {
    "the", "and", "for", "was", "were", "are", "with", "that", "this", "from",
    "during", "into", "over", "under", "have", "has", "had", "its", "their",
    "our", "according", "report", "reports", "document", "data", "demonstration",
}


# --------------------------------------------------------------------- helpers
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _prop(claim: "_Assertion | Claim") -> str:
    return (getattr(claim, "predicate", "") or getattr(claim, "subject", "") or "").strip().lower()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _relative_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-9)


def _canonical_measurement(unit: str, value: float) -> tuple[str, float] | None:
    converter = _TEMP_CONVERTERS.get(unit)
    if converter is None:
        return None
    try:
        return ("temperature", converter(float(value)))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _time_gap_minutes(a: "_Assertion", b: "_Assertion") -> float | None:
    if a.timestamp_value and b.timestamp_value:
        return abs((a.timestamp_value - b.timestamp_value).total_seconds()) / 60.0
    return None


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.year == 2000 and value.month == 1 and value.day == 1:
        return value.strftime("%H:%M")
    return value.strftime("%Y-%m-%d %H:%M")


def _fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return unit or "value"
    text = f"{value:g}"
    return f"{text} {unit}".strip()


def _describe_claim(claim: "_Assertion | Claim") -> str:
    if claim.claim_type == "measurement":
        return (
            f"{claim.subject or 'a quantity'} = "
            f"{_fmt_value(claim.numeric_value, claim.unit)}"
            + (f" at {_fmt_ts(claim.timestamp_value)}" if claim.timestamp_value else "")
        )
    if claim.claim_type == "state":
        state = claim.object_value or ("absent" if claim.polarity == "negative" else "present")
        return f"{claim.subject or 'a subject'} is '{state}'"
    return f"\"{claim.claim_text[:180]}\""


def _sentences_with_offsets(text: str) -> Iterable[tuple[str, int, int]]:
    """Yield ``(sentence, start, end)`` with exact offsets into ``text``.

    Mirrors :func:`claim_extraction.split_sentences` (split on sentence-ending
    punctuation followed by whitespace) without collapsing the original offsets.
    """
    if not text:
        return
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        end = match.start()
        segment = text[start:end]
        lead = len(segment) - len(segment.lstrip())
        body = segment.strip()
        if body:
            yield body, start + lead, start + lead + len(body)
        start = match.end()
    segment = text[start:]
    lead = len(segment) - len(segment.lstrip())
    body = segment.strip()
    if body:
        yield body, start + lead, start + lead + len(body)


def _normalized_index(text: str) -> tuple[str, list[int]]:
    """Return a whitespace-normalised copy of ``text`` and original indices."""
    chars: list[str] = []
    positions: list[int] = []
    prev_space = False
    for i, char in enumerate(text):
        if char.isspace():
            if prev_space:
                continue
            chars.append(" ")
            positions.append(i)
            prev_space = True
        else:
            chars.append(char.lower())
            positions.append(i)
            prev_space = False
    return "".join(chars), positions


def _locate(text: str, needle: str) -> tuple[int, int] | None:
    """Locate ``needle`` in ``text``, ignoring whitespace/case differences."""
    needle_n = _norm(needle)
    if not text or not needle_n:
        return None
    haystack, positions = _normalized_index(text)
    pos = haystack.find(needle_n)
    if pos == -1:
        return None
    return positions[pos], positions[pos + len(needle_n) - 1] + 1


def _page_for(start: int | None, page_map: list[dict]) -> int | None:
    if start is None:
        return None
    page = None
    for entry in page_map:
        entry_start = entry.get("start")
        if isinstance(entry_start, int) and entry_start <= start:
            if entry.get("page") is not None:
                page = entry["page"]
    return page


# ----------------------------------------------------------------- data models
@dataclass
class _Assertion:
    claim_text: str
    subject: str = ""
    predicate: str = ""
    object_value: str = ""
    numeric_value: float | None = None
    unit: str = ""
    polarity: str = "affirmative"
    claim_type: str = "statement"
    timestamp_value: datetime | None = None
    id: int | None = None
    document_id: int | None = None


def _signature(assertion: _Assertion) -> tuple:
    """Stable identity of an assertion, used to merge duplicate citations.

    The same fact often arrives twice: once as an extracted ``Claim`` and again
    as an investigator ``Evidence`` row that quotes that claim. Merging on the
    normalised value (rather than on wording) keeps one citation per fact.
    """
    subject = _norm(assertion.subject)
    prop = _norm(assertion.predicate)
    if assertion.claim_type == "measurement" and assertion.numeric_value is not None:
        converter = _canonical_measurement(assertion.unit or "", float(assertion.numeric_value))
        if converter is not None:
            return ("measurement", subject, prop, round(converter[1], 4), converter[0])
        return (
            "measurement",
            subject,
            prop,
            round(float(assertion.numeric_value), 4),
            _norm(assertion.unit),
        )
    if assertion.claim_type == "state":
        return (
            "state",
            subject,
            prop,
            assertion.polarity or "affirmative",
            _norm(assertion.object_value),
        )
    return ("text", assertion.claim_type, frozenset(_tokens(assertion.claim_text)))


def _from_claim(claim: Claim) -> _Assertion:
    return _Assertion(
        claim_text=claim.claim_text or "",
        subject=claim.subject or "",
        predicate=claim.predicate or "",
        object_value=claim.object_value or "",
        numeric_value=claim.numeric_value,
        unit=normalize_unit(claim.unit) if claim.unit else "",
        polarity=claim.polarity or "affirmative",
        claim_type=claim.claim_type or "statement",
        timestamp_value=claim.timestamp_value,
        id=claim.id,
        document_id=claim.document_id,
    )


def _from_extracted(extracted, document_id: int | None, sentence: str) -> _Assertion:
    return _Assertion(
        claim_text=sentence,
        subject=extracted.subject or "",
        predicate=extracted.predicate or "",
        object_value=extracted.object_value or "",
        numeric_value=extracted.numeric_value,
        unit=normalize_unit(extracted.unit) if extracted.unit else "",
        polarity=extracted.polarity or "affirmative",
        claim_type=extracted.claim_type or "statement",
        timestamp_value=extracted.timestamp_value,
        document_id=document_id,
    )


# --------------------------------------------------------------------- index
@dataclass
class VerificationIndex:
    """Pre-loaded records so a whole page of claims is verified with few queries."""

    claims: list[Claim]
    docs: dict[int, Document]
    contents: dict[int, DocumentContent]
    page_maps: dict[int, list[dict]]
    claim_to_conflicts: dict[int, set[int]]
    evidence_by_claim: dict[int, list[Evidence]]
    evidence_by_conflict: dict[int, list[Evidence]]
    document_count: int = 0
    claims_by_key: dict[tuple[str, str], list[Claim]] = field(default_factory=dict)
    _sentence_index: dict[int, dict[str, list[tuple[str, int, int, object]]]] = field(
        default_factory=dict
    )
    _source_cache: dict[int, dict] = field(default_factory=dict)

    def sentence_index(self, document_id: int) -> dict[str, list[tuple[str, int, int, object]]]:
        """Sentences of a document grouped by extracted subject (lazy, cached)."""
        if document_id in self._sentence_index:
            return self._sentence_index[document_id]
        grouped: dict[str, list[tuple[str, int, int, object]]] = defaultdict(list)
        content = self.contents.get(document_id)
        if content and content.text:
            for sentence, start, end in _sentences_with_offsets(content.text):
                for extracted in extract_claims(sentence):
                    if extracted.subject:
                        grouped[extracted.subject.strip().lower()].append(
                            (sentence, start, end, extracted)
                        )
        self._sentence_index[document_id] = dict(grouped)
        return self._sentence_index[document_id]


def build_scoped_index(
    db: Session,
    *,
    document_ids: Iterable[int] | None = None,
    conflict_ids: Iterable[int] | None = None,
) -> VerificationIndex:
    """Build an index limited to one investigation's documents and conflicts.

    Claims referenced by an in-scope conflict are always included (with their
    source document) so that the investigation's own conflicts remain
    explainable. Nothing outside those sets is loaded, which means verification
    performed with this index cannot cite another investigation's material.
    """
    doc_ids = {int(value) for value in (document_ids or []) if value is not None}
    conf_ids = {int(value) for value in (conflict_ids or []) if value is not None}

    conflicts: list[Conflict] = []
    if conf_ids:
        conflicts = list(
            db.execute(select(Conflict).where(Conflict.id.in_(conf_ids))).scalars()
        )

    conflict_claim_ids: set[int] = set()
    claim_to_conflicts: dict[int, set[int]] = defaultdict(set)
    for conflict in conflicts:
        for claim_id in (conflict.claim_a_id, conflict.claim_b_id):
            if claim_id:
                conflict_claim_ids.add(claim_id)
                claim_to_conflicts[claim_id].add(conflict.id)

    conditions = []
    if doc_ids:
        conditions.append(Claim.document_id.in_(doc_ids))
    if conflict_claim_ids:
        conditions.append(Claim.id.in_(conflict_claim_ids))
    if not conditions:
        return VerificationIndex(
            claims=[],
            docs={},
            contents={},
            page_maps={},
            claim_to_conflicts={},
            evidence_by_claim={},
            evidence_by_conflict={},
            document_count=0,
        )

    claims = list(
        db.execute(
            select(Claim).where(or_(*conditions)).order_by(Claim.id)
        ).scalars()
    )
    scoped_doc_ids = doc_ids | {claim.document_id for claim in claims if claim.document_id}
    docs = (
        {
            doc.id: doc
            for doc in db.execute(
                select(Document).where(Document.id.in_(scoped_doc_ids))
            ).scalars()
        }
        if scoped_doc_ids
        else {}
    )
    contents = (
        {
            content.document_id: content
            for content in db.execute(
                select(DocumentContent).where(
                    DocumentContent.document_id.in_(scoped_doc_ids)
                )
            ).scalars()
        }
        if scoped_doc_ids
        else {}
    )
    page_maps: dict[int, list[dict]] = {}
    for document_id, content in contents.items():
        try:
            parsed = json.loads(content.page_map or "[]")
        except (TypeError, json.JSONDecodeError):
            parsed = []
        page_maps[document_id] = parsed if isinstance(parsed, list) else []

    evidence_by_claim: dict[int, list[Evidence]] = defaultdict(list)
    evidence_by_conflict: dict[int, list[Evidence]] = defaultdict(list)
    if conf_ids:
        for evidence in db.execute(
            select(Evidence).where(Evidence.conflict_id.in_(conf_ids)).order_by(Evidence.id)
        ).scalars():
            evidence_by_conflict[evidence.conflict_id].append(evidence)
            if evidence.claim_id:
                evidence_by_claim[evidence.claim_id].append(evidence)

    index = VerificationIndex(
        claims=claims,
        docs=docs,
        contents=contents,
        page_maps=page_maps,
        claim_to_conflicts=dict(claim_to_conflicts),
        evidence_by_claim=dict(evidence_by_claim),
        evidence_by_conflict=dict(evidence_by_conflict),
        document_count=sum(
            1 for content in contents.values() if (content.text or "").strip()
        ),
    )
    for claim in claims:
        if claim.subject:
            index.claims_by_key.setdefault(
                (_norm(claim.subject), _prop(claim)), []
            ).append(claim)
    return index


def build_index(db: Session) -> VerificationIndex:
    claims = list(db.execute(select(Claim).order_by(Claim.id)).scalars())
    docs = {doc.id: doc for doc in db.execute(select(Document)).scalars()}
    contents = {c.document_id: c for c in db.execute(select(DocumentContent)).scalars()}
    page_maps: dict[int, list[dict]] = {}
    for document_id, content in contents.items():
        try:
            parsed = json.loads(content.page_map or "[]")
        except (TypeError, json.JSONDecodeError):
            parsed = []
        page_maps[document_id] = parsed if isinstance(parsed, list) else []

    claim_to_conflicts: dict[int, set[int]] = defaultdict(set)
    for conflict in db.execute(select(Conflict)).scalars():
        if conflict.claim_a_id:
            claim_to_conflicts[conflict.claim_a_id].add(conflict.id)
        if conflict.claim_b_id:
            claim_to_conflicts[conflict.claim_b_id].add(conflict.id)

    evidence_by_claim: dict[int, list[Evidence]] = defaultdict(list)
    evidence_by_conflict: dict[int, list[Evidence]] = defaultdict(list)
    for evidence in db.execute(select(Evidence).order_by(Evidence.id)).scalars():
        if evidence.claim_id:
            evidence_by_claim[evidence.claim_id].append(evidence)
        evidence_by_conflict[evidence.conflict_id].append(evidence)

    index = VerificationIndex(
        claims=claims,
        docs=docs,
        contents=contents,
        page_maps=page_maps,
        claim_to_conflicts=dict(claim_to_conflicts),
        evidence_by_claim=dict(evidence_by_claim),
        evidence_by_conflict=dict(evidence_by_conflict),
        document_count=sum(1 for c in contents.values() if (c.text or "").strip()),
    )
    for claim in claims:
        if claim.subject:
            index.claims_by_key.setdefault(
                (_norm(claim.subject), _prop(claim)), []
            ).append(claim)
    return index


# ------------------------------------------------------------------- sources
def _source_for_document(
    index: VerificationIndex,
    document_id: int | None,
    snippet: str,
    start: int | None = None,
    end: int | None = None,
) -> dict:
    doc = index.docs.get(document_id) if document_id else None
    filename = doc.filename if doc else None

    if start is None and document_id is not None and snippet:
        content = index.contents.get(document_id)
        if content and content.text:
            located = _locate(content.text, snippet)
            if located:
                start, end = located
    page = _page_for(start, index.page_maps.get(document_id, [])) if document_id else None

    if start is not None:
        location = (
            f"{filename} - page {page}"
            if page is not None
            else f"{filename} - characters {start}-{end}"
        )
    else:
        location = filename or "source unavailable"

    return {
        "document_id": document_id,
        "document_filename": filename,
        "page": page,
        "char_start": start,
        "char_end": end,
        "text_location": location,
        "snippet": (snippet or "")[:500],
        "link": f"/documents/{document_id}" if document_id else None,
    }


def _claim_source(index: VerificationIndex, claim: Claim) -> dict:
    if claim.id in index._source_cache:
        return index._source_cache[claim.id]
    source = _source_for_document(
        index, claim.document_id, claim.claim_text or ""
    )
    index._source_cache[claim.id] = source  # type: ignore[index]
    return source


def _evidence_source(index: VerificationIndex, evidence: Evidence) -> dict:
    snippet = evidence.description or ""
    quoted = re.search(r'"([^"]{8,})"', snippet)
    if quoted:
        snippet = quoted.group(1)
    if evidence.document_id:
        source = _source_for_document(index, evidence.document_id, snippet)
        if evidence.source_location:
            source["text_location"] = (
                f"{source['text_location']} (recorded as: {evidence.source_location})"
            )
        return source
    return {
        "document_id": None,
        "document_filename": None,
        "page": None,
        "char_start": None,
        "char_end": None,
        "text_location": evidence.source_location
        or evidence.source_reference
        or "recorded evidence",
        "snippet": snippet[:500],
        "link": None,
    }


# ------------------------------------------------------- public citation API
def source_for_document(
    index: VerificationIndex,
    document_id: int | None,
    snippet: str,
    start: int | None = None,
    end: int | None = None,
) -> dict:
    """Resolve a document citation (filename, page or character range, snippet).

    Public wrapper used by the investigation chat assistant so both features
    produce identical, verifiable source references.
    """
    return _source_for_document(index, document_id, snippet, start, end)


def claim_source(index: VerificationIndex, claim: Claim) -> dict:
    """Resolve the source document/location for a stored claim."""
    return _claim_source(index, claim)


def evidence_source(index: VerificationIndex, evidence: Evidence) -> dict:
    """Resolve the source document/location for a stored evidence row."""
    return _evidence_source(index, evidence)


# ---------------------------------------------------------------- comparison
def _compare(a: _Assertion, b: _Assertion) -> tuple[str, str] | None:
    """Compare two assertions.

    Returns ``(relation, reason)`` where relation is ``supports``,
    ``contradicts`` or ``neutral``, or ``None`` when the assertions are not about
    the same fact and must not be compared.
    """
    same_subject = bool(a.subject and b.subject and _norm(a.subject) == _norm(b.subject))
    same_property = bool(_prop(a) and _prop(a) == _prop(b))

    if not (same_subject and same_property):
        # Statement/event claims have no structured subject; require strong text
        # overlap before they may be compared, otherwise we would compare
        # unrelated sentences.
        if not (a.claim_type == b.claim_type and a.claim_type in ("statement", "event")):
            return None
        if _jaccard(a.claim_text, b.claim_text) < 0.65:
            return None

    # --- measurement vs measurement -------------------------------------
    if a.claim_type == "measurement" and b.claim_type == "measurement":
        if a.numeric_value is None or b.numeric_value is None:
            return (
                "neutral",
                "A measurement is missing its numeric value, so no comparison is possible.",
            )
        value_a, value_b = float(a.numeric_value), float(b.numeric_value)
        unit_a, unit_b = (a.unit or "").strip(), (b.unit or "").strip()
        if unit_a != unit_b:
            conv_a = _canonical_measurement(unit_a, value_a) if unit_a else None
            conv_b = _canonical_measurement(unit_b, value_b) if unit_b else None
            if conv_a and conv_b and conv_a[0] == conv_b[0]:
                value_a, value_b = conv_a[1], conv_b[1]
            else:
                return (
                    "neutral",
                    "The measurements use different or missing units "
                    f"({unit_a or 'unspecified'} vs {unit_b or 'unspecified'}) and "
                    "cannot be compared directly.",
                )
        diff = _relative_diff(value_a, value_b)
        if diff <= MEASUREMENT_TOLERANCE:
            return (
                "supports",
                "Reports the same value within the 2% comparison tolerance "
                f"({_fmt_value(b.numeric_value, b.unit)}).",
            )
        gap = _time_gap_minutes(a, b)
        if gap is not None and gap >= MIN_TEMPORAL_GAP_MINUTES:
            return (
                "neutral",
                f"Reports {_fmt_value(b.numeric_value, b.unit)} instead of "
                f"{_fmt_value(a.numeric_value, a.unit)}, but the readings are about "
                f"{gap:.0f} minutes apart; this may be a genuine change over time.",
            )
        if (a.timestamp_value is None) ^ (b.timestamp_value is None):
            return (
                "neutral",
                f"Reports a different value ({_fmt_value(b.numeric_value, b.unit)} vs "
                f"{_fmt_value(a.numeric_value, a.unit)}), but only one side records a "
                "timestamp, so contemporaneity is unknown.",
            )
        return (
            "contradicts",
            f"Reports {_fmt_value(b.numeric_value, b.unit)} for the same property and "
            f"time versus the claim's {_fmt_value(a.numeric_value, a.unit)} "
            f"({diff * 100:.0f}% difference).",
        )

    # --- state vs state --------------------------------------------------
    if a.claim_type == "state" and b.claim_type == "state":
        if a.polarity != b.polarity:
            return (
                "contradicts",
                "Asserts the opposite polarity "
                f"({b.polarity}: '{b.object_value or 'state'}') for the same subject.",
            )
        if a.object_value and b.object_value and _norm(a.object_value) != _norm(b.object_value):
            return (
                "contradicts",
                f"Describes the state differently ('{b.object_value}' vs "
                f"'{a.object_value}').",
            )
        return (
            "supports",
            f"Asserts the same state ('{b.object_value or 'present'}') for the same subject.",
        )

    # --- statement / event ----------------------------------------------
    if _jaccard(a.claim_text, b.claim_text) >= 0.65:
        return ("supports", "Closely restates the same assertion.")
    return None


def _evidence_independence(evidence: Evidence, claim: Claim) -> str:
    if evidence.origin == "user":
        return "user_supplied"
    if evidence.origin == "inferred":
        return "inferred"
    if evidence.document_id and evidence.document_id != claim.document_id:
        return "independent"
    return "same_source"


def _evidence_for(claim: Claim, index: VerificationIndex) -> list[Evidence]:
    seen: set[int] = set()
    items: list[Evidence] = []
    for evidence in index.evidence_by_claim.get(claim.id, []):
        if evidence.id not in seen:
            seen.add(evidence.id)
            items.append(evidence)
    for conflict_id in index.claim_to_conflicts.get(claim.id, set()):
        for evidence in index.evidence_by_conflict.get(conflict_id, []):
            if evidence.id not in seen:
                seen.add(evidence.id)
                items.append(evidence)
    return items


def _item(
    kind: str,
    record_id: int | None,
    relation: str,
    reason: str,
    text: str,
    independence: str,
    source: dict,
    timestamp: datetime | None,
) -> dict:
    return {
        "kind": kind,
        "record_id": record_id,
        "relation": relation,
        "reason": reason,
        "text": (text or "")[:1000],
        "independence": independence,
        "source": source,
        "timestamp_value": timestamp,
    }


def _collect_items(claim: Claim, index: VerificationIndex) -> list[dict]:
    """All comparable evidence for one claim, from claims, evidence and text.

    Every source is a real record or a verbatim sentence. Duplicate citations of
    the same fact (for example an investigator ``Evidence`` row that quotes a
    claim that is already compared directly) are merged so a fact is never
    double-counted as corroboration.
    """
    anchor = _from_claim(claim)
    anchor_signature = _signature(anchor)
    items: list[dict] = []
    seen: set[tuple[int | None, str, tuple]] = set()

    def add(
        kind: str,
        record_id: int | None,
        relation: str,
        reason: str,
        text: str,
        independence: str,
        source: dict,
        timestamp: datetime | None,
        assertion: _Assertion,
    ) -> None:
        signature = _signature(assertion)
        # A record that merely restates the claim itself is self-citation, not
        # corroboration; never count it in either direction.
        if signature == anchor_signature and source.get("document_id") == claim.document_id:
            return
        key = (source.get("document_id"), relation, signature)
        if key in seen:
            return
        seen.add(key)
        items.append(
            _item(
                kind,
                record_id,
                relation,
                reason,
                text,
                independence,
                source,
                timestamp,
            )
        )

    # 1) Other extracted claims with the same subject/property.
    if claim.subject:
        key = (_norm(claim.subject), _prop(claim))
        candidates = [
            c for c in index.claims_by_key.get(key, []) if c.id != claim.id
        ]
    else:
        candidates = [
            c
            for c in index.claims
            if c.id != claim.id and c.claim_type == claim.claim_type
        ]
    for candidate in candidates:
        candidate_assertion = _from_claim(candidate)
        comparison = _compare(anchor, candidate_assertion)
        if comparison is None:
            continue
        relation, reason = comparison
        independence = (
            "independent" if candidate.document_id != claim.document_id else "same_source"
        )
        add(
            "claim",
            candidate.id,
            relation,
            reason,
            candidate.claim_text,
            independence,
            _claim_source(index, candidate),
            candidate.timestamp_value,
            candidate_assertion,
        )

    # 2) Stored evidence rows linked to this claim or to its conflicts.
    for evidence in _evidence_for(claim, index):
        if evidence.evidence_type == "missing":
            continue  # surfaced through missing_information instead
        best: tuple[str, str, _Assertion] | None = None
        for extracted in extract_claims(evidence.description or ""):
            assertion = _from_extracted(
                extracted, evidence.document_id, evidence.description
            )
            comparison = _compare(anchor, assertion)
            if comparison is not None:
                best = (comparison[0], comparison[1], assertion)
                break
        if best is None:
            continue
        relation, reason, assertion = best
        add(
            "evidence",
            evidence.id,
            relation,
            reason,
            evidence.description,
            _evidence_independence(evidence, claim),
            _evidence_source(index, evidence),
            None,
            assertion,
        )

    # 3) Verbatim sentences from other uploaded documents. This catches facts in
    #    documents whose claims were not extracted (or were extracted partially).
    if claim.subject:
        subject_key = _norm(claim.subject)
        for document_id in index.contents:
            if document_id == claim.document_id:
                continue
            grouped = index.sentence_index(document_id)
            for sentence, start, end, extracted in grouped.get(subject_key, []):
                assertion = _from_extracted(extracted, document_id, sentence)
                comparison = _compare(anchor, assertion)
                if comparison is None:
                    continue
                relation, reason = comparison
                add(
                    "document",
                    None,
                    relation,
                    reason,
                    sentence,
                    "independent",
                    _source_for_document(index, document_id, sentence, start, end),
                    extracted.timestamp_value,
                    assertion,
                )
                # One item per sentence is enough; further extracted assertions
                # from the same sentence would duplicate the citation.
                break

    return items


# ----------------------------------------------------------------- verdict
def _distinct_sources(items: list[dict]) -> set[str]:
    """Count independent origins, not citation rows.

    Two rows quoting the same document are one source. Documents are keyed by
    id so two uploads with the same filename are still counted separately.
    """
    out: set[str] = set()
    for item in items:
        source = item.get("source") or {}
        if source.get("document_id") is not None:
            out.add(f"doc:{source['document_id']}")
        elif source.get("text_location"):
            out.add(f"loc:{source['text_location']}")
    return out


def _listing(items: list[dict], limit: int = 3) -> str:
    parts = []
    for item in items[:limit]:
        source = item.get("source") or {}
        location = source.get("text_location") or "source unknown"
        text = (item.get("text") or "").strip().replace("\n", " ")[:160]
        parts.append(f"{location} states \"{text}\"")
    return "; ".join(parts)


def _classify(
    claim: Claim, items: list[dict]
) -> tuple[str, list[dict], list[dict], list[dict], float]:
    supporting = [i for i in items if i["relation"] == "supports"]
    contradicting = [i for i in items if i["relation"] == "contradicts"]
    neutral = [i for i in items if i["relation"] == "neutral"]

    strong_support = [i for i in supporting if i["independence"] in ("independent", "user_supplied")]
    strong_contradict = [
        i for i in contradicting if i["independence"] in ("independent", "user_supplied")
    ]
    support_sources = len(_distinct_sources(strong_support))
    contradict_sources = len(_distinct_sources(strong_contradict))

    if strong_contradict and strong_support:
        verdict = FactVerdict.PARTIALLY_SUPPORTED.value
    elif strong_contradict:
        verdict = FactVerdict.CONTRADICTED.value
    elif strong_support:
        verdict = FactVerdict.SUPPORTED.value
    elif supporting or contradicting:
        verdict = FactVerdict.PARTIALLY_SUPPORTED.value
    else:
        verdict = FactVerdict.UNVERIFIED.value

    if verdict == FactVerdict.SUPPORTED.value:
        confidence = 0.55 + 0.12 * min(support_sources, 3)
    elif verdict == FactVerdict.CONTRADICTED.value:
        confidence = 0.55 + 0.20 * min(contradict_sources, 2)
    elif verdict == FactVerdict.PARTIALLY_SUPPORTED.value:
        confidence = 0.45 + 0.05 * min(
            support_sources + contradict_sources + len(supporting) + len(contradicting),
            4,
        )
    else:
        confidence = 0.20

    return (
        verdict,
        supporting,
        contradicting,
        neutral,
        round(_clamp(confidence), 3),
    )


def _missing_information(
    claim: Claim,
    verdict: str,
    supporting: list[dict],
    contradicting: list[dict],
    neutral: list[dict],
    evidence: list[Evidence],
    source: dict,
) -> list[str]:
    missing: list[str] = []

    def add(text: str) -> None:
        if text and text not in missing:
            missing.append(text)

    if not claim.subject:
        add(
            "No machine-readable subject was extracted, so matching this claim "
            "against other sources is limited."
        )
    if claim.claim_type == "measurement" and claim.numeric_value is None:
        add("The measurement has no numeric value to compare.")
    if claim.timestamp_value is None:
        add(
            "The claim carries no timestamp, so it is unclear whether other "
            "readings are contemporaneous."
        )
    for item in neutral:
        add((item.get("reason") or "").strip())

    strong_support = [
        i for i in supporting if i["independence"] in ("independent", "user_supplied")
    ]
    strong_contradict = [
        i for i in contradicting if i["independence"] in ("independent", "user_supplied")
    ]
    if not strong_support and not strong_contradict:
        add(
            "No independent source document or user-supplied evidence confirms or "
            "refutes this claim."
        )
    if verdict == FactVerdict.PARTIALLY_SUPPORTED.value and supporting and contradicting:
        add(
            "Supporting and contradicting evidence have not been reconciled; a "
            "human review or further context is required."
        )
    if verdict == FactVerdict.SUPPORTED.value and len(_distinct_sources(strong_support)) < 2:
        add(
            "Corroboration comes from a single independent source; additional "
            "independent confirmation would strengthen the verdict."
        )
    if claim.document_id and source.get("page") is None:
        doc = source.get("document_filename")
        if doc and doc.lower().endswith(".pdf"):
            add(
                "The exact page could not be determined from the stored page map; "
                "a character range is reported instead."
            )
    for evidence_item in evidence:
        if evidence_item.evidence_type == "missing":
            add(f"Recorded evidence gap: {evidence_item.description}")
    return missing


def _summary(verdict: str, supporting: list[dict], contradicting: list[dict]) -> str:
    strong_support = len(_distinct_sources(
        [i for i in supporting if i["independence"] in ("independent", "user_supplied")]
    ))
    strong_contradict = len(_distinct_sources(
        [i for i in contradicting if i["independence"] in ("independent", "user_supplied")]
    ))
    if verdict == FactVerdict.SUPPORTED.value:
        return f"Corroborated by {strong_support} independent source(s)."
    if verdict == FactVerdict.CONTRADICTED.value:
        return f"Contradicted by {strong_contradict} independent source(s)."
    if verdict == FactVerdict.PARTIALLY_SUPPORTED.value:
        return "Mixed or limited evidence; not conclusively supported or contradicted."
    return "No independent evidence found; marked Unverified."


def _explanation(
    claim: Claim,
    verdict: str,
    supporting: list[dict],
    contradicting: list[dict],
    neutral: list[dict],
) -> str:
    parts = [f"The claim asserts {_describe_claim(claim)}."]
    strong_support = [
        i for i in supporting if i["independence"] in ("independent", "user_supplied")
    ]
    strong_contradict = [
        i for i in contradicting if i["independence"] in ("independent", "user_supplied")
    ]
    weak_count = (len(supporting) - len(strong_support)) + (
        len(contradicting) - len(strong_contradict)
    )
    if strong_contradict:
        parts.append(f"Independent contradicting evidence: {_listing(strong_contradict)}.")
    if strong_support:
        parts.append(f"Independent supporting evidence: {_listing(strong_support)}.")
    if weak_count:
        parts.append(
            f"{weak_count} same-source restatement(s) were also found; they are not "
            "counted as independent corroboration."
        )
    if not strong_support and not strong_contradict:
        if supporting or contradicting:
            parts.append(
                "Only same-source material supports or opposes the claim, so it "
                "cannot be independently confirmed."
            )
        elif neutral:
            parts.append(
                "Only contextual evidence was found; none of it decisively "
                "confirms or refutes the assertion."
            )
        else:
            parts.append(
                "No other uploaded document, extracted claim or recorded evidence "
                "addresses this assertion."
            )
    if neutral and (supporting or contradicting):
        parts.append(
            f"{len(neutral)} additional item(s) could not be compared decisively "
            "(see contextual evidence)."
        )
    parts.append(
        f"Therefore the claim is classified as {VERDICT_LABELS[verdict]}."
    )
    return " ".join(parts)


# ------------------------------------------------------------------ public API
def verify_claim(
    db: Session,
    claim: Claim,
    *,
    index: VerificationIndex | None = None,
    use_llm: bool = False,
) -> dict:
    """Verify one claim and return an inspectable, JSON-ready result."""
    index = index or build_index(db)
    items = _collect_items(claim, index)
    verdict, supporting, contradicting, neutral, confidence = _classify(claim, items)
    evidence = _evidence_for(claim, index)
    source = _claim_source(index, claim)
    missing = _missing_information(
        claim, verdict, supporting, contradicting, neutral, evidence, source
    )

    result = {
        "claim_id": claim.id,
        "claim_text": claim.claim_text,
        "subject": claim.subject or "",
        "predicate": claim.predicate or "",
        "object_value": claim.object_value or "",
        "numeric_value": claim.numeric_value,
        "unit": claim.unit or "",
        "polarity": claim.polarity or "affirmative",
        "claim_type": claim.claim_type or "statement",
        "timestamp_value": claim.timestamp_value,
        "claim_confidence": round(float(claim.confidence), 3),
        "document_id": claim.document_id,
        "document_filename": source.get("document_filename"),
        "source": source,
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[verdict],
        "confidence": confidence,
        "summary": _summary(verdict, supporting, contradicting),
        "explanation": _explanation(claim, verdict, supporting, contradicting, neutral),
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "neutral_evidence": neutral,
        "missing_information": missing,
        "documents_considered": index.document_count,
        "claims_compared": len(items),
        "stored_evidence_considered": len(evidence),
        "method": "deterministic",
        "methodology": METHODOLOGY,
        "caveat": CAVEAT,
        "analysis_notes": [],
        "analyzed_at": datetime.now(timezone.utc),
    }
    if use_llm:
        result = _apply_llm_explanation(db, result)
    return result


def verify_claims(
    db: Session,
    claims: list[Claim],
    *,
    index: VerificationIndex | None = None,
) -> list[dict]:
    if not claims:
        return []
    index = index or build_index(db)
    return [verify_claim(db, claim, index=index) for claim in claims]


def verdict_counts(items: list[dict]) -> dict[str, int]:
    counts = {verdict.value: 0 for verdict in FactVerdict}
    for item in items:
        verdict = item.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return counts


def claims_for_investigation(db: Session, investigation: Investigation) -> list[Claim]:
    """Claims reachable from an investigation's documents or conflicts."""
    doc_ids = {doc.id for doc in investigation.documents}
    conflict_claim_ids: set[int] = set()
    for conflict in investigation.conflicts:
        if conflict.claim_a_id:
            conflict_claim_ids.add(conflict.claim_a_id)
        if conflict.claim_b_id:
            conflict_claim_ids.add(conflict.claim_b_id)
    conditions = []
    if doc_ids:
        conditions.append(Claim.document_id.in_(doc_ids))
    if conflict_claim_ids:
        conditions.append(Claim.id.in_(conflict_claim_ids))
    if not conditions:
        return []
    stmt = select(Claim).where(or_(*conditions)).order_by(Claim.id)
    return list(db.execute(stmt).scalars())


# ---------------------------------------------------------------- optional LLM
def _apply_llm_explanation(db: Session, result: dict) -> dict:
    """Rewrite the explanation with the LLM, validating every citation.

    The deterministic verdict is never changed. If the model cites a record that
    is not in the evidence list, the whole AI explanation is discarded so a
    fabricated citation can never reach the UI.
    """
    from . import settings_service
    from .llm_service import llm_service

    if not settings_service.llm_enabled(db):
        return result

    allowed: list[str] = []
    for item in (
        result["supporting_evidence"]
        + result["contradicting_evidence"]
        + result["neutral_evidence"]
    ):
        if item.get("record_id") is not None:
            allowed.append(f"{item['kind']}:{item['record_id']}")
        else:
            source = item.get("source") or {}
            allowed.append(
                f"doc:{source.get('document_id')}:{source.get('char_start')}"
            )
    evidence_payload = [
        {
            "citation": allowed[i] if i < len(allowed) else f"item:{i}",
            "relation": item.get("relation"),
            "text": (item.get("text") or "")[:220],
            "location": (item.get("source") or {}).get("text_location", ""),
        }
        for i, item in enumerate(
            result["supporting_evidence"]
            + result["contradicting_evidence"]
            + result["neutral_evidence"]
        )
    ]
    explanation = llm_service.explain_fact_verification(
        result["claim_text"],
        result["verdict"],
        evidence_payload,
        allowed,
    )
    if explanation is None or not explanation.explanation.strip():
        return result

    fabricated = [c for c in explanation.cited_citations if c not in allowed]
    if fabricated:
        result["analysis_notes"].append(
            "AI explanation rejected because it cited evidence that does not exist: "
            + ", ".join(sorted(set(fabricated)))
        )
        return result

    result["explanation"] = (
        result["explanation"]
        + " AI-assisted summary (citations validated): "
        + explanation.explanation.strip()
    )
    result["method"] = "ai_assisted"
    result["analysis_notes"].append(
        "AI-assisted summary accepted; every cited evidence reference exists."
    )
    return result
