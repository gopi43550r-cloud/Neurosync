"""Grounded investigation chat assistant.

The assistant is a deterministic question-answering layer over the data that is
already stored for one investigation: documents, claims, conflicts, evidence,
hypotheses and conclusions (the Blackboard records). It never calls a language
model, so it cannot generate a claim that is not backed by a row.

Design rules
------------
* **Scoped.** Every lookup is built from ``investigation.documents`` and
  ``investigation.conflicts``. Other investigations' records can never be cited.
* **Cited.** Each factual statement is assembled from a stored field and carries
  a numbered citation. Citations resolve to a document (with page or character
  location) whenever the record has one.
* **Explicit about absence.** If the stored records cannot answer the question,
  the response sets ``insufficient_information`` and says which information is
  missing instead of guessing.
* **No inference of intent beyond the question.** Entity resolution only accepts
  an explicit id, an unambiguous single record, or a clear token match. Otherwise
  the assistant asks the user to disambiguate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Claim, Conclusion, Conflict, Document, Evidence, Hypothesis, Investigation
from ..models.enums import ConclusionType
from .fact_verification_service import (
    VerificationIndex,
    build_scoped_index,
    claim_source,
    evidence_source,
    source_for_document,
    verify_claim,
)

METHODOLOGY = (
    "Answers are assembled from the investigation's own stored rows - documents, "
    "claims, conflicts, evidence, hypotheses and conclusions - and from the "
    "deterministic fact-verification engine. No language model is used, no record "
    "from another investigation is consulted, and every factual statement carries "
    "a numbered citation that resolves to a stored record and, where available, a "
    "source document with a page or character location."
)

CAVEAT = (
    "This assistant reports what the investigation's stored records contain. It "
    "does not certify that a source is truthful and it does not fill gaps with "
    "outside knowledge. When the records cannot answer a question the answer says "
    "so explicitly."
)

BASE_SUGGESTIONS = [
    "Summarise this investigation.",
    "Why was this conflict detected?",
    "Which document supports this claim?",
    "What evidence contradicts this hypothesis?",
    "Why is the investigation inconclusive?",
    "What additional evidence is required?",
]

_STOPWORDS = {
    "the", "and", "for", "was", "were", "are", "is", "been", "being", "with",
    "that", "this", "these", "those", "from", "during", "into", "over", "under",
    "have", "has", "had", "its", "their", "our", "which", "what", "why", "who",
    "when", "where", "how", "does", "did", "do", "about", "there", "here",
    "please", "tell", "show", "give", "explain", "according", "record", "records",
    "stored", "available", "current", "investigation", "conflict", "claim",
    "document", "documents", "evidence", "hypothesis", "conclusion", "source",
    "sources", "support", "supports", "supported", "supporting", "contradict",
    "contradicts", "contradicting", "detected", "detect", "detection", "flagged",
    "additional", "required", "require", "needed", "need", "more", "further",
    "missing", "inconclusive", "against", "this", "that", "any", "all", "can",
    "could", "would", "should", "not", "yes", "no", "it", "itself",
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9°%./-]*", re.IGNORECASE)


# --------------------------------------------------------------------- helpers
def _loads_dict(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(raw: str | None) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _as_text_list(raw: str | None) -> list[str]:
    values = []
    for item in _loads_list(raw):
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("question") or "").strip()
        else:
            text = str(item).strip()
        if text and text not in values:
            values.append(text)
    return values


def _tokens(text: str | None) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN_RE.findall((text or "").lower()):
        if match in _STOPWORDS:
            continue
        if len(match) < 3 and not any(char.isdigit() for char in match):
            continue
        tokens.add(match)
    return tokens


def _overlap_score(question_tokens: set[str], text: str | None) -> float:
    if not question_tokens:
        return 0.0
    text_tokens = _tokens(text)
    if not text_tokens:
        return 0.0
    shared = question_tokens & text_tokens
    score = len(shared) / len(question_tokens)
    lowered = (text or "").lower()
    for token in shared:
        if token in lowered:
            score += 0.05
    return score


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = (value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _explicit_id(question: str, noun: str) -> int | None:
    match = re.search(rf"\b{noun}\s*(?:#|id\s*)?\s*(\d+)\b", question, re.IGNORECASE)
    return int(match.group(1)) if match else None


# ------------------------------------------------------------------- citations
@dataclass
class CitationRegistry:
    """Assigns stable, de-duplicated citation numbers."""

    items: list[dict] = field(default_factory=list)
    _keys: dict[tuple, int] = field(default_factory=dict)

    def add(
        self,
        *,
        kind: str,
        record_id: int | None,
        label: str,
        source: dict,
        snippet: str | None = None,
    ) -> int:
        key = (
            kind,
            record_id,
            source.get("document_id"),
            source.get("char_start"),
            source.get("char_end"),
        )
        if key in self._keys:
            return self._keys[key]
        number = len(self.items) + 1
        self._keys[key] = number
        self.items.append(
            {
                "number": number,
                "kind": kind,
                "record_id": record_id,
                "label": label,
                "document_id": source.get("document_id"),
                "document_filename": source.get("document_filename"),
                "page": source.get("page"),
                "char_start": source.get("char_start"),
                "char_end": source.get("char_end"),
                "text_location": source.get("text_location") or "stored record",
                "snippet": (snippet if snippet is not None else source.get("snippet") or "")[:500],
                "link": source.get("link"),
            }
        )
        return number


def _record_source(text_location: str, snippet: str = "") -> dict:
    return {
        "document_id": None,
        "document_filename": None,
        "page": None,
        "char_start": None,
        "char_end": None,
        "text_location": text_location,
        "snippet": snippet[:500],
        "link": None,
    }


# --------------------------------------------------------------------- context
@dataclass
class ChatContext:
    db: Session
    investigation: Investigation
    documents: list[Document]
    conflicts: list[Conflict]
    conclusions: list[Conclusion]
    index: VerificationIndex
    claims: list[Claim]
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]

    @property
    def claims_by_id(self) -> dict[int, Claim]:
        return {claim.id: claim for claim in self.claims}

    @property
    def conflicts_by_id(self) -> dict[int, Conflict]:
        return {conflict.id: conflict for conflict in self.conflicts}

    @property
    def hypotheses_by_id(self) -> dict[int, Hypothesis]:
        return {hypothesis.id: hypothesis for hypothesis in self.hypotheses}


def _latest_conclusions(conclusions: list[Conclusion]) -> list[Conclusion]:
    """Newest non-superseded conclusion per conflict (plus overall ones)."""
    latest: dict[int | None, Conclusion] = {}
    for conclusion in sorted(conclusions, key=lambda item: item.id):
        if conclusion.superseded_at is not None:
            continue
        latest[conclusion.conflict_id] = conclusion
    return sorted(latest.values(), key=lambda item: item.id, reverse=True)


def build_context(db: Session, investigation: Investigation) -> ChatContext:
    documents = sorted(investigation.documents, key=lambda item: item.id)
    conflicts = sorted(investigation.conflicts, key=lambda item: item.id)
    document_ids = {document.id for document in documents}
    conflict_ids = {conflict.id for conflict in conflicts}

    index = build_scoped_index(
        db, document_ids=document_ids, conflict_ids=conflict_ids
    )

    hypotheses: list[Hypothesis] = []
    if conflict_ids:
        hypotheses = list(
            db.execute(
                select(Hypothesis)
                .where(Hypothesis.conflict_id.in_(conflict_ids))
                .order_by(Hypothesis.id)
            ).scalars()
        )
    hypotheses.sort(key=lambda item: (-item.support_score, -item.id))

    conclusions = list(
        db.execute(
            select(Conclusion)
            .where(Conclusion.investigation_id == investigation.id)
            .order_by(Conclusion.id)
        ).scalars()
    )

    evidence_seen: set[int] = set()
    evidence: list[Evidence] = []
    for rows in index.evidence_by_conflict.values():
        for row in rows:
            if row.id not in evidence_seen:
                evidence_seen.add(row.id)
                evidence.append(row)
    evidence.sort(key=lambda item: item.id)

    return ChatContext(
        db=db,
        investigation=investigation,
        documents=documents,
        conflicts=conflicts,
        conclusions=_latest_conclusions(conclusions),
        index=index,
        claims=index.claims,
        evidence=evidence,
        hypotheses=hypotheses,
    )


# --------------------------------------------------------------- citation util
def _cite_claim(
    ctx: ChatContext, registry: CitationRegistry, claim: Claim | None, snippet: str | None = None
) -> int | None:
    if claim is None:
        return None
    source = claim_source(ctx.index, claim)
    return registry.add(
        kind="claim",
        record_id=claim.id,
        label=f"Claim #{claim.id}",
        source=source,
        snippet=snippet if snippet is not None else claim.claim_text,
    )


def _cite_document(
    ctx: ChatContext, registry: CitationRegistry, document: Document
) -> int:
    content = ctx.index.contents.get(document.id)
    excerpt = (content.text or "")[:280] if content else ""
    if excerpt:
        source = source_for_document(ctx.index, document.id, excerpt, 0, len(excerpt))
    else:
        source = source_for_document(ctx.index, document.id, "")
    return registry.add(
        kind="document",
        record_id=document.id,
        label=f"Document “{document.filename}”",
        source=source,
        snippet=excerpt,
    )


def _cite_conflict(registry: CitationRegistry, conflict: Conflict) -> int:
    return registry.add(
        kind="conflict",
        record_id=conflict.id,
        label=f"Conflict #{conflict.id}",
        source=_record_source(f"stored conflict record #{conflict.id}", conflict.description),
        snippet=conflict.description,
    )


def _cite_hypothesis(registry: CitationRegistry, hypothesis: Hypothesis) -> int:
    return registry.add(
        kind="hypothesis",
        record_id=hypothesis.id,
        label=f"Hypothesis #{hypothesis.id}",
        source=_record_source(f"stored hypothesis record #{hypothesis.id}", hypothesis.title),
        snippet=f"{hypothesis.title}. {hypothesis.explanation}".strip(),
    )


def _cite_conclusion(registry: CitationRegistry, conclusion: Conclusion) -> int:
    return registry.add(
        kind="conclusion",
        record_id=conclusion.id,
        label=f"Conclusion #{conclusion.id}",
        source=_record_source(
            f"stored conclusion record #{conclusion.id}", conclusion.conclusion
        ),
        snippet=conclusion.conclusion,
    )


def _cite_evidence(
    ctx: ChatContext, registry: CitationRegistry, evidence: Evidence
) -> int:
    source = evidence_source(ctx.index, evidence)
    return registry.add(
        kind="evidence",
        record_id=evidence.id,
        label=f"Evidence #{evidence.id}",
        source=source,
        snippet=evidence.description,
    )


def _cite_investigation(registry: CitationRegistry, investigation: Investigation) -> int:
    return registry.add(
        kind="investigation",
        record_id=investigation.id,
        label=f"Investigation #{investigation.id}",
        source=_record_source(
            f"stored investigation record #{investigation.id}",
            investigation.research_question,
        ),
        snippet=investigation.research_question,
    )


# -------------------------------------------------------------------- entities
def resolve_conflict(
    ctx: ChatContext, question: str, hint_id: int | None
) -> tuple[Conflict | None, list[Conflict]]:
    if hint_id is not None:
        match = ctx.conflicts_by_id.get(hint_id)
        return (match, []) if match else (None, [])
    explicit = _explicit_id(question, "conflict")
    if explicit is not None:
        match = ctx.conflicts_by_id.get(explicit)
        return (match, []) if match else (None, [])
    if len(ctx.conflicts) == 1:
        return ctx.conflicts[0], []
    question_tokens = _tokens(question)
    scored = [
        (
            max(
                _overlap_score(question_tokens, conflict.description),
                _overlap_score(question_tokens, _loads_dict(conflict.meta).get("subject", "")),
                _overlap_score(
                    question_tokens,
                    " ".join(
                        claim.claim_text
                        for claim in (
                            ctx.claims_by_id.get(conflict.claim_a_id),
                            ctx.claims_by_id.get(conflict.claim_b_id),
                        )
                        if claim is not None
                    ),
                ),
            ),
            conflict,
        )
        for conflict in ctx.conflicts
    ]
    scored = [pair for pair in scored if pair[0] >= 0.34]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    if scored:
        return scored[0][1], []
    return None, ctx.conflicts


def resolve_claim(
    ctx: ChatContext, question: str, hint_id: int | None, conflict: Conflict | None
) -> tuple[Claim | None, list[Claim]]:
    candidates = [
        claim
        for claim in ctx.claims
        if conflict is None or claim.id in (conflict.claim_a_id, conflict.claim_b_id)
    ]
    if not candidates:
        candidates = ctx.claims
    if hint_id is not None:
        # An explicit claim id is authoritative even when a conflict hint was
        # also supplied; it must still belong to this investigation.
        match = ctx.claims_by_id.get(hint_id)
        return (match, []) if match else (None, [])
    explicit = _explicit_id(question, "claim")
    if explicit is not None:
        match = next((claim for claim in candidates if claim.id == explicit), None)
        return (match, []) if match else (None, [])
    if len(candidates) == 1:
        return candidates[0], []
    question_tokens = _tokens(question)
    scored = [
        (
            max(
                _overlap_score(question_tokens, claim.claim_text),
                _overlap_score(question_tokens, claim.subject),
                _overlap_score(question_tokens, claim.object_value),
            ),
            claim,
        )
        for claim in candidates
    ]
    scored = [pair for pair in scored if pair[0] >= 0.34]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    if scored:
        return scored[0][1], []
    return None, candidates


def resolve_hypothesis(
    ctx: ChatContext, question: str, hint_id: int | None, conflict: Conflict | None
) -> tuple[Hypothesis | None, list[Hypothesis]]:
    candidates = [
        hypothesis
        for hypothesis in ctx.hypotheses
        if conflict is None or hypothesis.conflict_id == conflict.id
    ]
    if not candidates:
        candidates = ctx.hypotheses
    if hint_id is not None:
        # An explicit hypothesis id is always resolved within this
        # investigation, never from another investigation's records.
        match = ctx.hypotheses_by_id.get(hint_id)
        return (match, []) if match else (None, [])
    explicit = _explicit_id(question, "hypothesis")
    if explicit is not None:
        match = next((item for item in candidates if item.id == explicit), None)
        return (match, []) if match else (None, [])
    if len(candidates) == 1:
        return candidates[0], []
    question_tokens = _tokens(question)
    scored = [
        (
            max(
                _overlap_score(question_tokens, hypothesis.title),
                _overlap_score(question_tokens, hypothesis.explanation),
            ),
            hypothesis,
        )
        for hypothesis in candidates
    ]
    scored = [pair for pair in scored if pair[0] >= 0.34]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    if scored:
        return scored[0][1], []
    return None, candidates


# ---------------------------------------------------------------------- intent
def detect_intent(
    question: str,
    *,
    conflict_id: int | None = None,
    claim_id: int | None = None,
    hypothesis_id: int | None = None,
) -> str:
    text = question.lower()

    if any(
        phrase in text
        for phrase in (
            "what additional",
            "what else",
            "what evidence is required",
            "what evidence is needed",
            "what evidence would",
            "what is missing",
            "what information is missing",
            "what further",
            "what more",
            "further evidence",
            "more evidence",
            "additional evidence",
            "next step",
            "what should we",
            "what needs to be",
        )
    ):
        return "missing_evidence"

    if any(
        phrase in text
        for phrase in (
            "inconclusive",
            "not conclusive",
            "not been resolved",
            "not resolved",
            "unresolved",
            "no conclusion",
            "cannot conclude",
            "why not resolved",
            "why hasn't",
            "why has not",
        )
    ):
        return "investigation_inconclusive"

    if hypothesis_id is not None:
        return "hypothesis_contradiction"
    if claim_id is not None:
        return "claim_support"
    if conflict_id is not None:
        return "conflict_detected"

    if "hypothesis" in text and any(
        word in text
        for word in ("contradict", "against", "refute", "undermine", "counter", "weaken")
    ):
        return "hypothesis_contradiction"
    if any(phrase in text for phrase in ("evidence against", "what contradicts")):
        return "hypothesis_contradiction"

    if any(
        phrase in text
        for phrase in (
            "supports this claim",
            "support this claim",
            "which document supports",
            "what document supports",
            "which source supports",
            "what source supports",
            "source for the claim",
            "source for this claim",
            "evidence for the claim",
            "evidence for this claim",
            "corroborat",
            "who supports",
        )
    ):
        return "claim_support"
    if "claim" in text and any(
        word in text for word in ("support", "document", "source", "evidence")
    ):
        return "claim_support"

    if any(
        phrase in text
        for phrase in (
            "why was this conflict",
            "why is this conflict",
            "why was it detected",
            "why detected",
            "why was this flagged",
            "why was it flagged",
            "what caused the conflict",
            "explain the conflict",
            "explain this conflict",
        )
    ):
        return "conflict_detected"
    if "conflict" in text and any(
        word in text for word in ("why", "detect", "flag", "cause", "explain")
    ):
        return "conflict_detected"

    if any(
        phrase in text
        for phrase in ("summar", "overview", "what do we know", "what has been found", "recap", "status")
    ):
        return "summary"

    if "document" in text and any(
        word in text for word in ("available", "list", "attached", "uploaded", "which", "what")
    ):
        return "document_lookup"

    return "record_search"


# --------------------------------------------------------------- answer drafts
@dataclass
class AnswerDraft:
    text: str
    insufficient: bool = False
    missing: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)


def _clarify_conflict(
    ctx: ChatContext, registry: CitationRegistry, candidates: list[Conflict]
) -> AnswerDraft:
    if not ctx.conflicts:
        return AnswerDraft(
            text=(
                "No conflict has been recorded for this investigation, so there is "
                "no stored conflict to explain. The assistant will not describe a "
                "conflict that does not exist."
            ),
            insufficient=True,
            missing=["No conflict record exists for this investigation."],
            follow_ups=["Summarise this investigation.", "What documents are available?"],
        )
    lines = [
        f"The investigation contains {len(ctx.conflicts)} conflict(s) and the "
        "question does not identify a specific one by id or distinctive wording. "
        "The stored candidates are:"
    ]
    for conflict in ctx.conflicts[:6]:
        number = _cite_conflict(registry, conflict)
        lines.append(
            f"- Conflict #{conflict.id} — {conflict.conflict_type}, "
            f"status {conflict.status}: {conflict.description or 'no description stored'} [{number}]"
        )
    lines.append("Please identify one conflict by id (for example, conflict #3).")
    return AnswerDraft(
        text="\n".join(lines),
        insufficient=True,
        missing=["The question does not identify a single stored conflict."],
        follow_ups=(
            [
                f"Which document supports claim #{ctx.conflicts[0].claim_a_id}?"
            ]
            if ctx.conflicts
            else []
        )
        + ["Summarise this investigation."],
    )


def _answer_conflict(
    ctx: ChatContext, registry: CitationRegistry, question: str, hint_id: int | None
) -> AnswerDraft:
    conflict, candidates = resolve_conflict(ctx, question, hint_id)
    if conflict is None:
        if hint_id is not None:
            return AnswerDraft(
                text=(
                    f"Conflict #{hint_id} is not part of this investigation. The "
                    "assistant only reads this investigation's stored conflicts and "
                    "will not answer from another investigation's record."
                ),
                insufficient=True,
                missing=[
                    f"Conflict #{hint_id} is not linked to investigation "
                    f"#{ctx.investigation.id}."
                ],
                follow_ups=["Summarise this investigation."],
            )
        return _clarify_conflict(ctx, registry, candidates)

    number = _cite_conflict(registry, conflict)
    meta = _loads_dict(conflict.meta)
    lines = [
        f"Conflict #{conflict.id} was recorded as `{conflict.conflict_type}` with "
        f"{conflict.severity} severity and confidence {conflict.confidence:.2f}; "
        f"the detection method was `{conflict.detection_method}`. [{number}]"
    ]
    if conflict.description:
        lines.append(f"The stored detector explanation is: {conflict.description} [{number}]")
    if meta.get("reason"):
        lines.append(f"The stored detection metadata records the reason `{meta['reason']}`. [{number}]")
    if meta.get("units"):
        lines.append(f"Recorded units for the compared values: {meta['units']}. [{number}]")
    if meta.get("relative_diff") is not None:
        lines.append(f"Recorded relative difference: {meta['relative_diff']}. [{number}]")

    claim_a = ctx.claims_by_id.get(conflict.claim_a_id)
    claim_b = ctx.claims_by_id.get(conflict.claim_b_id)
    if claim_a and claim_b:
        number_a = _cite_claim(ctx, registry, claim_a)
        number_b = _cite_claim(ctx, registry, claim_b)
        file_a = claim_a.source_reference or f"document #{claim_a.document_id}"
        file_b = claim_b.source_reference or f"document #{claim_b.document_id}"
        lines.append(
            f"Claim A (#{claim_a.id}), recorded in {file_a}, states: "
            f"“{claim_a.claim_text}” [{number_a}]"
        )
        lines.append(
            f"Claim B (#{claim_b.id}), recorded in {file_b}, states: "
            f"“{claim_b.claim_text}” [{number_b}]"
        )
    elif not conflict.description:
        return AnswerDraft(
            text=(
                f"Conflict #{conflict.id} is stored, but neither the detector "
                "description nor both compared claims can be read from the records, "
                "so the reason it was detected cannot be reported."
            ),
            insufficient=True,
            missing=["The conflict's explanation and compared claims are unavailable."],
            follow_ups=["Summarise this investigation."],
        )

    attached = ctx.index.evidence_by_conflict.get(conflict.id, [])
    if attached:
        cited = []
        for evidence in attached[:3]:
            cited.append(f"[{_cite_evidence(ctx, registry, evidence)}]")
        lines.append(
            f"{len(attached)} evidence row(s) are attached to this conflict. "
            f"The first {min(len(attached), 3)} citation(s): {' '.join(cited)}"
        )
    else:
        lines.append(
            "No evidence row is attached to this conflict in the stored records, "
            "so the detector's explanation is the only recorded rationale."
        )

    lines.append(
        "This answer quotes the stored conflict, claim and evidence records; it "
        "does not propose a cause that the records do not contain."
    )
    return AnswerDraft(
        text="\n".join(lines),
        follow_ups=_dedupe(
            [
                f"Which document supports claim #{claim_a.id}?" if claim_a else "",
                f"What evidence contradicts hypothesis #{ctx.hypotheses[0].id}?"
                if ctx.hypotheses
                else "",
                "Why is the investigation inconclusive?",
                "What additional evidence is required?",
            ]
        ),
    )


def _claim_value(claim: Claim) -> str:
    if claim.claim_type == "measurement" and claim.numeric_value is not None:
        return f"{claim.numeric_value:g} {claim.unit}".strip()
    if claim.object_value:
        return claim.object_value
    return claim.claim_text


def _answer_claim_support(
    ctx: ChatContext,
    registry: CitationRegistry,
    question: str,
    claim_id: int | None,
    conflict_id: int | None,
) -> AnswerDraft:
    conflict = ctx.conflicts_by_id.get(conflict_id) if conflict_id else None
    claim, candidates = resolve_claim(ctx, question, claim_id, conflict)
    if claim is None:
        if claim_id is not None:
            return AnswerDraft(
                text=(
                    f"Claim #{claim_id} is not part of this investigation. The "
                    "assistant only reads this investigation's stored claims and will "
                    "not answer from another investigation's record."
                ),
                insufficient=True,
                missing=[
                    f"Claim #{claim_id} is not linked to investigation "
                    f"#{ctx.investigation.id}."
                ],
                follow_ups=["Summarise this investigation."],
            )
        if not ctx.claims:
            return AnswerDraft(
                text=(
                    "No claim has been extracted for this investigation, so no "
                    "document can be identified as supporting a claim."
                ),
                insufficient=True,
                missing=["No claim records exist for this investigation."],
                follow_ups=["Summarise this investigation.", "What documents are available?"],
            )
        lines = [
            f"The investigation contains {len(ctx.claims)} claim(s) and the question "
            "does not identify a specific one. The stored candidates are:"
        ]
        for candidate in ctx.claims[:6]:
            number = _cite_claim(ctx, registry, candidate)
            lines.append(f"- Claim #{candidate.id}: “{candidate.claim_text}” [{number}]")
        lines.append("Please identify one claim by id (for example, claim #4).")
        return AnswerDraft(
            text="\n".join(lines),
            insufficient=True,
            missing=["The question does not identify a single stored claim."],
            follow_ups=[
                f"Which document supports claim #{candidate.id}?"
                for candidate in ctx.claims[:3]
            ],
        )

    verification = verify_claim(ctx.db, claim, index=ctx.index)
    source = verification.get("source") or claim_source(ctx.index, claim)
    number = registry.add(
        kind="claim",
        record_id=claim.id,
        label=f"Claim #{claim.id}",
        source=source,
        snippet=claim.claim_text,
    )
    lines = [
        f"Claim #{claim.id} states: “{claim.claim_text}” "
        f"and was extracted from {source.get('text_location') or 'a stored source'}. [{number}]"
    ]
    lines.append(
        f"The deterministic verifier's verdict is {verification['verdict_label']} "
        f"(confidence {verification['confidence']:.2f}): {verification['summary']} [{number}]"
    )
    if verification.get("explanation"):
        lines.append(f"{verification['explanation']} [{number}]")

    supporting = verification.get("supporting_evidence") or []
    independent = [
        item
        for item in supporting
        if item.get("independence") in ("independent", "user_supplied")
    ]
    same_source = [item for item in supporting if item not in independent]

    if independent:
        lines.append(
            f"{len(independent)} independent stored item(s) support this claim:"
        )
        for item in independent[:6]:
            item_source = item.get("source") or {}
            cite = registry.add(
                kind=item.get("kind") or "record",
                record_id=item.get("record_id"),
                label=(
                    f"{str(item.get('kind') or 'record').title()} "
                    f"#{item.get('record_id')}"
                    if item.get("record_id")
                    else "Stored sentence"
                ),
                source=item_source,
                snippet=item.get("text") or item_source.get("snippet"),
            )
            location = item_source.get("text_location") or "stored record"
            lines.append(
                f"- {location}: “{item.get('text') or item_source.get('snippet') or ''}” "
                f"— {item.get('reason') or 'related stored content'} [{cite}]"
            )
    else:
        lines.append(
            "No independent stored document or evidence row supports this claim. "
            "Same-source restatements are not counted as corroboration."
        )

    if same_source:
        lines.append(
            f"{len(same_source)} additional same-source item(s) repeat or mention the "
            "claim; they are not independent support."
        )

    contradicting = verification.get("contradicting_evidence") or []
    independent_contradicting = [
        item
        for item in contradicting
        if item.get("independence") in ("independent", "user_supplied")
    ]
    if independent_contradicting:
        lines.append(
            f"{len(independent_contradicting)} independent stored item(s) contradict it:"
        )
        for item in independent_contradicting[:6]:
            item_source = item.get("source") or {}
            cite = registry.add(
                kind=item.get("kind") or "record",
                record_id=item.get("record_id"),
                label=(
                    f"{str(item.get('kind') or 'record').title()} "
                    f"#{item.get('record_id')}"
                    if item.get("record_id")
                    else "Stored sentence"
                ),
                source=item_source,
                snippet=item.get("text") or item_source.get("snippet"),
            )
            location = item_source.get("text_location") or "stored record"
            lines.append(
                f"- {location}: “{item.get('text') or item_source.get('snippet') or ''}” "
                f"— {item.get('reason') or 'related stored content'} [{cite}]"
            )

    missing = _dedupe(list(verification.get("missing_information") or []))
    if missing:
        lines.append("Recorded gaps for this claim:")
        lines.extend(f"- {item}" for item in missing[:8])

    insufficient = not independent
    return AnswerDraft(
        text="\n".join(lines),
        insufficient=insufficient,
        missing=missing,
        follow_ups=_dedupe(
            [
                f"What evidence contradicts claim #{claim.id}?"
                if independent_contradicting
                else "",
                "What additional evidence is required?",
                "Why is the investigation inconclusive?",
            ]
        ),
    )


def _answer_hypothesis_contradiction(
    ctx: ChatContext,
    registry: CitationRegistry,
    question: str,
    hypothesis_id: int | None,
    conflict_id: int | None,
    claim_id: int | None,
) -> AnswerDraft:
    conflict = ctx.conflicts_by_id.get(conflict_id) if conflict_id else None
    if conflict is None and claim_id is not None:
        claim = ctx.claims_by_id.get(claim_id)
        if claim is not None:
            conflict = next(
                (
                    item
                    for item in ctx.conflicts
                    if claim.id in (item.claim_a_id, item.claim_b_id)
                ),
                None,
            )
    hypothesis, candidates = resolve_hypothesis(ctx, question, hypothesis_id, conflict)
    if hypothesis is None:
        if hypothesis_id is not None:
            return AnswerDraft(
                text=(
                    f"Hypothesis #{hypothesis_id} is not part of this investigation. "
                    "The assistant only reads this investigation's stored hypotheses "
                    "and will not answer from another investigation's record."
                ),
                insufficient=True,
                missing=[
                    f"Hypothesis #{hypothesis_id} is not linked to investigation "
                    f"#{ctx.investigation.id}."
                ],
                follow_ups=["Summarise this investigation."],
            )
        if not ctx.hypotheses:
            return AnswerDraft(
                text=(
                    "No hypothesis has been recorded for this investigation's "
                    "conflicts, so there is no stored hypothesis to test for "
                    "contradicting evidence."
                ),
                insufficient=True,
                missing=["No hypothesis record exists for this investigation."],
                follow_ups=["Summarise this investigation.", "What additional evidence is required?"],
            )
        lines = [
            f"The investigation contains {len(ctx.hypotheses)} hypothesis/hypotheses "
            "and the question does not identify a specific one. The stored candidates are:"
        ]
        for candidate in ctx.hypotheses[:6]:
            number = _cite_hypothesis(registry, candidate)
            lines.append(
                f"- Hypothesis #{candidate.id} (conflict #{candidate.conflict_id}, "
                f"status {candidate.status}): “{candidate.title}” [{number}]"
            )
        lines.append("Please identify one hypothesis by id (for example, hypothesis #2).")
        return AnswerDraft(
            text="\n".join(lines),
            insufficient=True,
            missing=["The question does not identify a single stored hypothesis."],
            follow_ups=[
                f"What evidence contradicts hypothesis #{candidate.id}?"
                for candidate in ctx.hypotheses[:3]
            ],
        )

    number = _cite_hypothesis(registry, hypothesis)
    lines = [
        f"Hypothesis #{hypothesis.id} for conflict #{hypothesis.conflict_id} states: "
        f"“{hypothesis.title}”. {hypothesis.explanation} "
        f"Its stored status is `{hypothesis.status}` with support score "
        f"{hypothesis.support_score:.2f}. [{number}]"
    ]

    ids = set(_loads_list(hypothesis.contradicting_evidence_ids))
    contradicting = [
        evidence
        for evidence in ctx.evidence
        if evidence.id in ids or evidence.contradicts_hypothesis_id == hypothesis.id
    ]
    seen: set[int] = set()
    contradicting = [
        evidence
        for evidence in contradicting
        if not (evidence.id in seen or seen.add(evidence.id))
    ]
    supporting = [
        evidence
        for evidence in ctx.evidence
        if evidence.supports_hypothesis_id == hypothesis.id
    ]

    if contradicting:
        lines.append(
            f"{len(contradicting)} stored evidence row(s) contradict this hypothesis:"
        )
        for evidence in contradicting[:8]:
            cite = _cite_evidence(ctx, registry, evidence)
            source = evidence_source(ctx.index, evidence)
            lines.append(
                f"- Evidence #{evidence.id} ({evidence.evidence_type}, "
                f"reliability {evidence.reliability_score:.2f}) from "
                f"{source.get('text_location') or 'a stored record'}: "
                f"“{evidence.description}” [{cite}]"
            )
    else:
        lines.append(
            "No stored evidence row is recorded as contradicting this hypothesis. "
            "The absence of recorded counter-evidence is not proof that the "
            "hypothesis is correct."
        )

    if supporting:
        cited = []
        for evidence in supporting[:3]:
            cited.append(f"[{_cite_evidence(ctx, registry, evidence)}]")
        lines.append(
            f"{len(supporting)} stored evidence row(s) support it. "
            f"First {min(len(supporting), 3)} citation(s): {' '.join(cited)}"
        )

    assumptions = _as_text_list(hypothesis.assumptions)
    missing = _as_text_list(hypothesis.missing_information)
    if assumptions:
        lines.append("Recorded assumptions that have not been independently confirmed:")
        lines.extend(f"- {item}" for item in assumptions[:6])
    if missing:
        lines.append("Recorded missing information for this hypothesis:")
        lines.extend(f"- {item}" for item in missing[:8])

    return AnswerDraft(
        text="\n".join(lines),
        insufficient=not bool(contradicting),
        missing=_dedupe(
            missing
            + [
                "No stored evidence row is recorded as contradicting this hypothesis."
            ]
            if not contradicting
            else missing
        ),
        follow_ups=_dedupe(
            [
                f"Which document supports claim #{claim_id}?" if claim_id else "",
                "What additional evidence is required?",
                "Why is the investigation inconclusive?",
            ]
        ),
    )


def _answer_inconclusive(
    ctx: ChatContext, registry: CitationRegistry
) -> AnswerDraft:
    if not ctx.conclusions:
        lines = [
            "No conclusion has been recorded for this investigation yet, so neither "
            "a conclusive nor an inconclusive result is stored. The question cannot "
            "be answered from the current records."
        ]
        if ctx.conflicts:
            lines.append("The current stored conflict statuses are:")
            for conflict in ctx.conflicts[:8]:
                number = _cite_conflict(registry, conflict)
                lines.append(
                    f"- Conflict #{conflict.id} ({conflict.conflict_type}) is "
                    f"`{conflict.status}`. [{number}]"
                )
        lines.append(
            "Run or complete the investigation to produce a conclusion record, or "
            "ask what additional evidence is required."
        )
        return AnswerDraft(
            text="\n".join(lines),
            insufficient=True,
            missing=["No conclusion record exists for this investigation."],
            follow_ups=["What additional evidence is required?", "Summarise this investigation."],
        )

    unresolved_types = {
        ConclusionType.INCONCLUSIVE.value,
        ConclusionType.HUMAN_REVIEW.value,
        ConclusionType.TENTATIVE.value,
    }
    unresolved = [
        conclusion
        for conclusion in ctx.conclusions
        if conclusion.decision_type in unresolved_types
    ]
    if not unresolved:
        lines = [
            "No stored conclusion labels this investigation inconclusive. The latest "
            "recorded conclusion(s) are:"
        ]
        for conclusion in ctx.conclusions[:6]:
            number = _cite_conclusion(registry, conclusion)
            lines.append(
                f"- Conflict #{conclusion.conflict_id or '—'}: "
                f"`{conclusion.decision_type}` (confidence {conclusion.confidence:.2f}). "
                f"“{conclusion.conclusion}” [{number}]"
            )
        return AnswerDraft(
            text="\n".join(lines),
            follow_ups=[
                "What additional evidence is required?",
                "Summarise this investigation.",
            ],
        )

    lines = [
        f"{len(unresolved)} stored conclusion(s) record this investigation as not "
        "fully resolved:"
    ]
    for conclusion in unresolved[:6]:
        number = _cite_conclusion(registry, conclusion)
        lines.append(
            f"- Conflict #{conclusion.conflict_id or '—'}: the latest conclusion is "
            f"`{conclusion.decision_type}` (confidence {conclusion.confidence:.2f}). "
            f"Stored conclusion: “{conclusion.conclusion}” [{number}]"
        )
        unanswered = _as_text_list(conclusion.unresolved_questions)
        if unanswered:
            lines.append(
                "  Unresolved questions recorded for this conflict: "
                + "; ".join(unanswered[:6])
                + f" [{number}]"
            )
        limitations = _as_text_list(conclusion.limitations)
        if limitations:
            lines.append(
                "  Recorded limitations: "
                + "; ".join(limitations[:4])
                + f" [{number}]"
            )
        conflict = ctx.conflicts_by_id.get(conclusion.conflict_id or -1)
        if conflict is not None:
            claim_a = ctx.claims_by_id.get(conflict.claim_a_id)
            claim_b = ctx.claims_by_id.get(conflict.claim_b_id)
            cited = [
                str(number)
                for number in (
                    _cite_claim(ctx, registry, claim_a),
                    _cite_claim(ctx, registry, claim_b),
                )
                if number is not None
            ]
            if cited:
                lines.append(
                    "  The conflicting claims are held in the cited source "
                    f"documents: {' '.join(f'[{item}]' for item in cited)}"
                )

    lines.append(
        "These are the reasons stored in the conclusion records; the assistant "
        "does not add a cause that the investigation did not record."
    )
    missing = _dedupe(
        [
            item
            for conclusion in unresolved
            for item in _as_text_list(conclusion.unresolved_questions)
        ]
    )
    return AnswerDraft(
        text="\n".join(lines),
        missing=missing,
        follow_ups=[
            "What additional evidence is required?",
            "What evidence contradicts the leading hypothesis?"
            if ctx.hypotheses
            else "Summarise this investigation.",
            "Which document supports the contested claim?" if ctx.claims else "",
        ],
    )


def _missing_requirements(ctx: ChatContext) -> list[tuple[str, object, str]]:
    """Collect recorded gaps as ``(text, record, kind)`` tuples."""
    items: list[tuple[str, object, str]] = []
    seen: set[str] = set()

    def add(text: str, record: object, kind: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        items.append((cleaned, record, kind))

    for hypothesis in ctx.hypotheses:
        for text in _as_text_list(hypothesis.missing_information):
            add(text, hypothesis, "hypothesis")
        for text in _as_text_list(hypothesis.assumptions):
            add(f"Confirm the assumption: {text}", hypothesis, "hypothesis")

    for conclusion in ctx.conclusions:
        for text in _as_text_list(conclusion.unresolved_questions):
            add(text, conclusion, "conclusion")

    for evidence in ctx.evidence:
        if evidence.evidence_type == "missing":
            add(evidence.description, evidence, "evidence")

    for conflict in ctx.conflicts:
        if not ctx.index.evidence_by_conflict.get(conflict.id):
            add(
                f"Conflict #{conflict.id} has no recorded evidence rows; evidence "
                "that would resolve it is still required.",
                conflict,
                "conflict",
            )

    for claim in ctx.claims[:25]:
        verification = verify_claim(ctx.db, claim, index=ctx.index)
        for text in verification.get("missing_information") or []:
            add(text, claim, "claim")

    return items


def _answer_missing_evidence(
    ctx: ChatContext, registry: CitationRegistry
) -> AnswerDraft:
    items = _missing_requirements(ctx)
    if not items:
        return AnswerDraft(
            text=(
                "The stored investigation records do not list any missing information "
                "or additional-evidence requirement. That is not a guarantee that the "
                "evidence is complete: it means no gap was recorded."
            ),
            insufficient=True,
            missing=["No missing-information or additional-evidence record is stored."],
            follow_ups=["Why is the investigation inconclusive?", "Summarise this investigation."],
        )

    lines = [
        "The following gaps are recorded in the investigation's own rows. These are "
        "the only additional items the assistant can report; it does not invent "
        "requirements."
    ]
    missing: list[str] = []
    for text, record, kind in items[:14]:
        if kind == "hypothesis":
            assert isinstance(record, Hypothesis)
            number = _cite_hypothesis(registry, record)
        elif kind == "conclusion":
            assert isinstance(record, Conclusion)
            number = _cite_conclusion(registry, record)
        elif kind == "evidence":
            assert isinstance(record, Evidence)
            number = _cite_evidence(ctx, registry, record)
        elif kind == "conflict":
            assert isinstance(record, Conflict)
            number = _cite_conflict(registry, record)
        else:
            assert isinstance(record, Claim)
            number = _cite_claim(ctx, registry, record)
            text = f"For claim #{record.id} (“{record.claim_text}”): {text}"
        lines.append(f"- {text} [{number}]")
        missing.append(text)

    if len(items) > 14:
        lines.append(
            f"{len(items) - 14} further recorded gap(s) are not shown to keep the "
            "answer readable; the full text remains in the cited records."
        )
    return AnswerDraft(
        text="\n".join(lines),
        missing=missing,
        follow_ups=[
            "Why is the investigation inconclusive?",
            "What evidence contradicts the leading hypothesis?"
            if ctx.hypotheses
            else "Summarise this investigation.",
        ],
    )


def _answer_summary(ctx: ChatContext, registry: CitationRegistry) -> AnswerDraft:
    investigation = ctx.investigation
    inv_cite = _cite_investigation(registry, investigation)
    open_conflicts = sum(1 for item in ctx.conflicts if item.status == "open")
    resolved_conflicts = sum(1 for item in ctx.conflicts if item.status == "resolved")
    lines = [
        f"Investigation #{investigation.id}, “{investigation.name}”, is stored with "
        f"status `{investigation.status}`. Its recorded research question is: "
        f"“{investigation.research_question or 'not recorded'}”. [{inv_cite}]",
        f"The investigation's blackboard currently contains {len(ctx.documents)} "
        f"source document(s), {len(ctx.claims)} claim(s), {len(ctx.conflicts)} "
        f"conflict(s) ({open_conflicts} open, {resolved_conflicts} resolved), "
        f"{len(ctx.evidence)} evidence row(s), {len(ctx.hypotheses)} hypothesis/"
        f"hypotheses and {len(ctx.conclusions)} current conclusion(s). [{inv_cite}]",
    ]

    if ctx.documents:
        lines.append(
            "Source documents: "
            + ", ".join(
                f"“{document.filename}” [{_cite_document(ctx, registry, document)}]"
                for document in ctx.documents[:8]
            )
            + "."
        )
        if len(ctx.documents) > 8:
            lines.append(
                f"{len(ctx.documents) - 8} further document(s) are attached but not "
                "listed here."
            )
    else:
        lines.append(
            "No source documents are attached to this investigation, so no document "
            "reference can be provided."
        )

    if ctx.conflicts:
        lines.append("Recorded conflicts:")
        for conflict in ctx.conflicts[:6]:
            number = _cite_conflict(registry, conflict)
            lines.append(
                f"- Conflict #{conflict.id} — {conflict.conflict_type}, severity "
                f"{conflict.severity}, status `{conflict.status}`: "
                f"{conflict.description or 'no description stored'} [{number}]"
            )

    if ctx.conclusions:
        lines.append("Latest conclusions:")
        for conclusion in ctx.conclusions[:6]:
            number = _cite_conclusion(registry, conclusion)
            lines.append(
                f"- Conflict #{conclusion.conflict_id or '—'}: "
                f"`{conclusion.decision_type}` — “{conclusion.conclusion}” [{number}]"
            )

    if not ctx.documents and not ctx.conflicts and not ctx.claims:
        return AnswerDraft(
            text="\n".join(lines),
            insufficient=True,
            missing=[
                "No documents, claims or conflicts are stored for this investigation."
            ],
            follow_ups=["What documents are available?", "What additional evidence is required?"],
        )
    return AnswerDraft(
        text="\n".join(lines),
        follow_ups=[
            "Why is the investigation inconclusive?",
            "What additional evidence is required?",
            "Which document supports this claim?",
        ],
    )


def _answer_documents(ctx: ChatContext, registry: CitationRegistry) -> AnswerDraft:
    if not ctx.documents:
        return AnswerDraft(
            text=(
                "No document is attached to this investigation, so there are no "
                "source documents to list."
            ),
            insufficient=True,
            missing=["No documents are linked to this investigation."],
            follow_ups=["Summarise this investigation."],
        )
    lines = [f"{len(ctx.documents)} source document(s) are attached to this investigation:"]
    for document in ctx.documents[:20]:
        number = _cite_document(ctx, registry, document)
        claim_count = sum(1 for claim in ctx.claims if claim.document_id == document.id)
        metadata = _loads_dict(document.source_metadata)
        recorded = []
        if metadata.get("author"):
            recorded.append(f"author {metadata['author']}")
        if metadata.get("organization"):
            recorded.append(f"organization {metadata['organization']}")
        if metadata.get("publication_date"):
            recorded.append(f"publication date {metadata['publication_date']}")
        lines.append(
            f"- “{document.filename}” ({document.file_type}, status "
            f"`{document.status}`, {claim_count} extracted claim(s)"
            + (f"; recorded {', '.join(recorded)}" if recorded else "; no author, organization or publication date recorded")
            + f"). [{number}]"
        )
    if len(ctx.documents) > 20:
        lines.append(f"{len(ctx.documents) - 20} further document(s) are not shown.")
    return AnswerDraft(
        text="\n".join(lines),
        follow_ups=[
            "Which document supports this claim?",
            "Why is the investigation inconclusive?",
        ],
    )


def _answer_search(
    ctx: ChatContext, registry: CitationRegistry, question: str
) -> AnswerDraft:
    tokens = _tokens(question)
    if not tokens:
        return AnswerDraft(
            text=(
                "The question does not contain a distinctive term that can be matched "
                "against the investigation's stored records. Please name a claim, "
                "conflict, hypothesis, document or subject."
            ),
            insufficient=True,
            missing=["No searchable term was found in the question."],
            follow_ups=BASE_SUGGESTIONS[:4],
        )

    results: list[tuple[float, str, int, object]] = []

    for document in ctx.documents:
        score = _overlap_score(tokens, document.filename)
        if score >= 0.34:
            results.append((score, "document", document.id, document))
    for claim in ctx.claims:
        score = max(
            _overlap_score(tokens, claim.claim_text),
            _overlap_score(tokens, claim.subject),
            _overlap_score(tokens, claim.object_value),
        )
        if score >= 0.34:
            results.append((score, "claim", claim.id, claim))
    for conflict in ctx.conflicts:
        score = max(
            _overlap_score(tokens, conflict.description),
            _overlap_score(tokens, conflict.conflict_type),
        )
        if score >= 0.34:
            results.append((score, "conflict", conflict.id, conflict))
    for hypothesis in ctx.hypotheses:
        score = max(
            _overlap_score(tokens, hypothesis.title),
            _overlap_score(tokens, hypothesis.explanation),
        )
        if score >= 0.34:
            results.append((score, "hypothesis", hypothesis.id, hypothesis))
    for conclusion in ctx.conclusions:
        score = _overlap_score(tokens, conclusion.conclusion)
        if score >= 0.34:
            results.append((score, "conclusion", conclusion.id, conclusion))
    for evidence in ctx.evidence:
        score = _overlap_score(tokens, evidence.description)
        if score >= 0.34:
            results.append((score, "evidence", evidence.id, evidence))

    results.sort(key=lambda item: (-item[0], item[1], item[2]))
    if not results:
        return AnswerDraft(
            text=(
                f"No stored record in this investigation matches the terms "
                f"{', '.join(sorted(tokens))}. The assistant cannot answer from the "
                "current investigation data."
            ),
            insufficient=True,
            missing=[
                "No stored document, claim, conflict, evidence, hypothesis or "
                "conclusion matches the question."
            ],
            follow_ups=BASE_SUGGESTIONS[:4],
        )

    lines = [
        f"I searched only this investigation's stored records for the terms "
        f"{', '.join(sorted(tokens))}. {len(results)} record(s) matched:"
    ]
    for score, kind, record_id, record in results[:8]:
        if kind == "document":
            document = record
            assert isinstance(document, Document)
            number = _cite_document(ctx, registry, document)
            lines.append(f"- Document “{document.filename}” [{number}]")
        elif kind == "claim":
            claim = record
            assert isinstance(claim, Claim)
            number = _cite_claim(ctx, registry, claim)
            lines.append(f"- Claim #{claim.id}: “{claim.claim_text}” [{number}]")
        elif kind == "conflict":
            conflict = record
            assert isinstance(conflict, Conflict)
            number = _cite_conflict(registry, conflict)
            lines.append(
                f"- Conflict #{conflict.id} ({conflict.conflict_type}, "
                f"{conflict.status}): {conflict.description or 'no description stored'} "
                f"[{number}]"
            )
        elif kind == "hypothesis":
            hypothesis = record
            assert isinstance(hypothesis, Hypothesis)
            number = _cite_hypothesis(registry, hypothesis)
            lines.append(
                f"- Hypothesis #{hypothesis.id} (conflict #{hypothesis.conflict_id}): "
                f"“{hypothesis.title}” [{number}]"
            )
        elif kind == "conclusion":
            conclusion = record
            assert isinstance(conclusion, Conclusion)
            number = _cite_conclusion(registry, conclusion)
            lines.append(
                f"- Conclusion #{conclusion.id} (`{conclusion.decision_type}`): "
                f"“{conclusion.conclusion}” [{number}]"
            )
        else:
            evidence = record
            assert isinstance(evidence, Evidence)
            number = _cite_evidence(ctx, registry, evidence)
            source = evidence_source(ctx.index, evidence)
            lines.append(
                f"- Evidence #{evidence.id} from "
                f"{source.get('text_location') or 'a stored record'}: "
                f"“{evidence.description}” [{number}]"
            )
    if len(results) > 8:
        lines.append(f"{len(results) - 8} further matching record(s) are not shown.")
    lines.append(
        "These are stored records, not generated text. If none of them addresses the "
        "question, the investigation data does not contain the answer."
    )
    return AnswerDraft(text="\n".join(lines), follow_ups=BASE_SUGGESTIONS[:4])


# ------------------------------------------------------------------ public API
def answer_question(
    db: Session,
    investigation: Investigation,
    question: str,
    *,
    conflict_id: int | None = None,
    claim_id: int | None = None,
    hypothesis_id: int | None = None,
    document_id: int | None = None,
) -> dict:
    """Answer one question from the investigation's stored rows only."""
    ctx = build_context(db, investigation)
    registry = CitationRegistry()

    # A document hint only *disambiguates* which document is meant; it never
    # injects content from outside the investigation.
    if document_id is not None and document_id not in {
        document.id for document in ctx.documents
    }:
        document_id = None

    intent = detect_intent(
        question,
        conflict_id=conflict_id,
        claim_id=claim_id,
        hypothesis_id=hypothesis_id,
    )

    if intent == "missing_evidence":
        draft = _answer_missing_evidence(ctx, registry)
    elif intent == "investigation_inconclusive":
        draft = _answer_inconclusive(ctx, registry)
    elif intent == "hypothesis_contradiction":
        draft = _answer_hypothesis_contradiction(
            ctx, registry, question, hypothesis_id, conflict_id, claim_id
        )
    elif intent == "claim_support":
        draft = _answer_claim_support(ctx, registry, question, claim_id, conflict_id)
    elif intent == "conflict_detected":
        draft = _answer_conflict(ctx, registry, question, conflict_id)
    elif intent == "summary":
        draft = _answer_summary(ctx, registry)
    elif intent == "document_lookup":
        draft = _answer_documents(ctx, registry)
    else:
        draft = _answer_search(ctx, registry, question)

    # A grounded answer must cite at least one stored record. If a handler could
    # not, make that explicit rather than returning uncited prose.
    if not registry.items and not draft.insufficient:
        draft.insufficient = True
        draft.missing.append("No stored record could be cited for this answer.")

    data_sources = {
        "documents": len(ctx.documents),
        "claims": len(ctx.claims),
        "conflicts": len(ctx.conflicts),
        "evidence": len(ctx.evidence),
        "hypotheses": len(ctx.hypotheses),
        "conclusions": len(ctx.conclusions),
    }

    return {
        "investigation_id": investigation.id,
        "investigation_name": investigation.name,
        "question": question,
        "intent": intent,
        "answer": draft.text,
        "insufficient_information": draft.insufficient,
        "missing_information": _dedupe(draft.missing),
        "citations": registry.items,
        "follow_up_questions": _dedupe(draft.follow_ups)[:5],
        "data_sources": data_sources,
        "methodology": METHODOLOGY,
        "caveat": CAVEAT,
        "analyzed_at": datetime.now(timezone.utc),
    }


def suggestions_for(investigation: Investigation, context: ChatContext | None = None) -> list[str]:
    """Context-aware example questions that the records can actually answer."""
    suggestions = list(BASE_SUGGESTIONS)
    if context is not None:
        if context.conflicts:
            conflict = context.conflicts[0]
            suggestions.insert(1, f"Why was conflict #{conflict.id} detected?")
        if context.claims:
            claim = context.claims[0]
            suggestions.insert(2, f"Which document supports claim #{claim.id}?")
        if context.hypotheses:
            hypothesis = context.hypotheses[0]
            suggestions.insert(
                3, f"What evidence contradicts hypothesis #{hypothesis.id}?"
            )
        if not context.documents:
            suggestions = [
                "Summarise this investigation.",
                "What additional evidence is required?",
            ]
    return _dedupe(suggestions)[:8]
