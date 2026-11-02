"""Evidence-grounded source credibility analysis.

The analyzer answers one question per uploaded source: *what can actually be
established about this source from the records NeuroSync stores?* It evaluates
six factors:

1. **Source authenticity** — is the stored artifact internally consistent with
   its intake record (checksum, stored file, size, extraction status)?
2. **Author or organization** — is a creator recorded in ``source_metadata``?
3. **Publication date** — is a real publication date recorded (not the upload
   time)?
4. **Evidence quality** — how much direct, structured evidence does the source
   actually contribute (content, claims, measurements, calibration records)?
5. **Source traceability** — can every part of the source be traced to a stored
   artifact, checksum, page/character location, or source reference?
6. **Consistency with other available sources** — do the source's extracted
   claims agree or disagree with the other documents, using the same
   deterministic comparison engine as claim verification?

Design rules
------------
* **Nothing is invented.** Every value shown is a stored field, a verbatim
  metadata value, a filesystem fact, or a real cross-record comparison.
  Credentials are never inferred from filenames or document text.
* **Unknown is not low.** A factor whose inputs are missing has ``score=None``
  and status ``unknown``. It is excluded from the aggregate, never scored as
  zero. Sources with too little assessable information are labelled
  ``unverifiable`` instead of receiving a negative score.
* **A bounded documentation indicator, not a trust rating.** The aggregate is a
  transparent weighted mean over assessed factors. It says how much of the
  source can be checked, not whether the source tells the truth.
* **Computed on read.** No table is added and no snapshot can go stale; the
  result always reflects the current documents, claims and evidence.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import UPLOAD_DIR
from ..models import Claim, Document, DocumentContent, Evidence, Investigation, Observation
from .fact_verification_service import VerificationIndex, build_index, verify_claim

FACTOR_WEIGHTS: dict[str, float] = {
    "authenticity": 0.20,
    "author": 0.15,
    "publication_date": 0.15,
    "evidence_quality": 0.20,
    "traceability": 0.15,
    "consistency": 0.15,
}

FACTOR_LABELS: dict[str, str] = {
    "authenticity": "Source authenticity",
    "author": "Author / organization",
    "publication_date": "Publication date",
    "evidence_quality": "Evidence quality",
    "traceability": "Source traceability",
    "consistency": "Consistency with other sources",
}

LEVEL_LABELS: dict[str, str] = {
    "well_documented": "Well documented",
    "partially_documented": "Partially documented",
    "limited_documentation": "Limited documentation",
    "unverifiable": "Unverifiable",
}

# A source must expose at least this much of the weighted checklist before an
# aggregate is shown. Otherwise it is marked unverifiable rather than "low".
MIN_ASSESSABLE_WEIGHT = 0.40
MIN_COVERAGE_FOR_WELL_DOCUMENTED = 0.55

METHODOLOGY = (
    "Six factors are assessed from stored records only: source authenticity "
    "(checksum, stored file, size and extraction status), author or organization "
    "(source metadata), publication date (source metadata, never the upload "
    "time), evidence quality (content, extracted claims and linked evidence), "
    "source traceability (checksum, page/character locations and source "
    "references) and consistency (the source's extracted claims compared with "
    "other documents using the claim-verification engine). Unknown factors are "
    "excluded from the aggregate and reported explicitly."
)

CAVEAT = (
    "This is a bounded documentation/provenance indicator, not a verified trust "
    "rating or a calibrated probability. NeuroSync cannot confirm that a "
    "recorded author, organization, date or identifier is genuine, and it never "
    "infers credentials from filenames or document text. A low coverage means "
    "the source is unverifiable, not that it is false."
)

# Metadata keys are matched case-insensitively after normalising separators.
_METADATA_ALIASES: dict[str, tuple[str, ...]] = {
    "author": (
        "author", "authors", "creator", "created_by", "byline", "inspector",
        "technician", "prepared_by", "writer", "analyst", "reporter",
        "signed_by", "signatory",
    ),
    "organization": (
        "organization", "organisation", "org", "publisher", "company",
        "institution", "agency", "department", "owner", "manufacturer",
        "issued_by", "produced_by",
    ),
    "publication_date": (
        "publication_date", "published", "published_at", "date_published",
        "issued", "issue_date", "report_date", "date", "created",
        "creation_date", "publication", "date_issued",
    ),
    "source_type": (
        "source_type", "document_type", "doctype", "type", "category",
        "genre", "format", "medium",
    ),
    "identifier": (
        "doi", "isbn", "issn", "url", "uri", "reference", "ref",
        "accession_number", "report_number", "document_number", "identifier",
        "citation", "permalink", "catalog_number", "id",
    ),
    "version": ("version", "revision", "rev", "edition"),
    "signature": (
        "signature", "signed_by", "signatory", "verified_by", "approved_by",
        "seal", "certification", "certificate",
    ),
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%B %d, %Y",
)

_MAX_EXAMPLES = 5


# --------------------------------------------------------------------- helpers
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalise_key(key: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(key).strip().lower())


def _parse_metadata(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stringify(value) -> str | None:
    """Return a trimmed scalar as text; never stringify booleans or objects."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [_stringify(item) for item in value]
        text = ", ".join(part for part in parts if part)
        return text or None
    if isinstance(value, dict):
        return None
    text = str(value).strip()
    return text or None


def _metadata_value(metadata: dict, aliases: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Find the first non-empty alias value. Returns ``(value, original_key)``."""
    for key, value in metadata.items():
        if _normalise_key(key) in aliases:
            text = _stringify(value)
            if text:
                return text, str(key)
    return None, None


def _date_parts(value) -> tuple[date | None, str | None, str, str | None]:
    """Parse a recorded publication date without guessing.

    Returns ``(parsed, iso_value, precision, raw)``. ``precision`` is ``day``,
    ``month`` or ``year``. Unparseable input returns ``(None, None, "", raw)``.
    """
    if value is None or isinstance(value, bool):
        return None, None, "", None
    raw = _stringify(value)
    if not raw:
        return None, None, "", None

    if isinstance(value, datetime):
        return value.date(), value.date().isoformat(), "day", raw
    if isinstance(value, date):
        return value, value.isoformat(), "day", raw

    text = raw.strip()
    if re.fullmatch(r"\d{4}", text):
        try:
            return date(int(text), 1, 1), f"{int(text):04d}", "year", raw
        except ValueError:
            return None, None, "", raw
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            year, month = (int(part) for part in text.split("-"))
            return date(year, month, 1), f"{year:04d}-{month:02d}", "month", raw
        except ValueError:
            return None, None, "", raw

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date(), text, "day", raw
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
            return parsed, parsed.isoformat(), "day", raw
        except ValueError:
            continue
    return None, None, "", raw


def _factor(
    key: str,
    *,
    status: str,
    score: float | None,
    summary: str,
    explanation: str,
    inputs: list[str] | None = None,
    missing: list[str] | None = None,
) -> dict:
    return {
        "key": key,
        "label": FACTOR_LABELS[key],
        "status": status,
        "score": None if score is None else round(_clamp(score), 3),
        "summary": summary,
        "explanation": explanation,
        "inputs": inputs or [],
        "missing": missing or [],
    }


# ---------------------------------------------------------------------- context
@dataclass
class SourceCredibilityContext:
    documents: list[Document]
    contents: dict[int, DocumentContent]
    claims_by_doc: dict[int, list[Claim]]
    evidence_by_doc: dict[int, list[Evidence]]
    observations_by_doc: dict[int, int]
    verification_index: VerificationIndex
    duplicate_checksums: dict[str, int] = field(default_factory=dict)
    file_state: dict[int, tuple[bool, int | None]] = field(default_factory=dict)


def _file_state(doc: Document) -> tuple[bool, int | None]:
    if not doc.stored_filename:
        return False, None
    try:
        path = Path(UPLOAD_DIR) / doc.stored_filename
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False, None
    try:
        if not path.is_file():
            return False, None
        return True, path.stat().st_size
    except OSError:  # pragma: no cover - permission/race
        return False, None


def build_context(db: Session, documents: list[Document] | None = None) -> SourceCredibilityContext:
    """Load everything the factor functions need with a bounded query count."""
    docs = documents if documents is not None else list(
        db.execute(select(Document).order_by(Document.id)).scalars()
    )
    doc_ids = [doc.id for doc in docs]

    contents: dict[int, DocumentContent] = {}
    claims_by_doc: dict[int, list[Claim]] = defaultdict(list)
    evidence_by_doc: dict[int, list[Evidence]] = defaultdict(list)
    observations: Counter[int] = Counter()

    if doc_ids:
        for content in db.execute(
            select(DocumentContent).where(DocumentContent.document_id.in_(doc_ids))
        ).scalars():
            contents[content.document_id] = content
        for claim in db.execute(
            select(Claim).where(Claim.document_id.in_(doc_ids)).order_by(Claim.id)
        ).scalars():
            claims_by_doc[claim.document_id].append(claim)
        for evidence in db.execute(
            select(Evidence).where(Evidence.document_id.in_(doc_ids)).order_by(Evidence.id)
        ).scalars():
            evidence_by_doc[evidence.document_id].append(evidence)
        for document_id, count in db.execute(
            select(Observation.document_id, func.count())
            .where(Observation.document_id.in_(doc_ids))
            .group_by(Observation.document_id)
        ).all():
            observations[int(document_id)] = int(count)

    duplicate_checksums: Counter[str] = Counter()
    for checksum, count in db.execute(
        select(Document.checksum, func.count())
        .where(Document.checksum != "")
        .group_by(Document.checksum)
    ).all():
        if checksum:
            duplicate_checksums[str(checksum)] = int(count)

    return SourceCredibilityContext(
        documents=docs,
        contents=contents,
        claims_by_doc=dict(claims_by_doc),
        evidence_by_doc=dict(evidence_by_doc),
        observations_by_doc=dict(observations),
        verification_index=build_index(db),
        duplicate_checksums=dict(duplicate_checksums),
        file_state={doc.id: _file_state(doc) for doc in docs},
    )


# ------------------------------------------------------------------ factor impl
def _authenticity_factor(
    doc: Document,
    ctx: SourceCredibilityContext,
    *,
    content_available: bool,
    warnings: list[str],
) -> dict:
    checksum = (doc.checksum or "").strip()
    checksum_valid = bool(re.fullmatch(r"[0-9a-fA-F]{64}", checksum))
    file_present, actual_size = ctx.file_state.get(doc.id, (False, None))
    size_matches = bool(file_present and actual_size is not None and actual_size == doc.file_size)

    inputs: list[str] = []
    missing: list[str] = []
    score = 0.0

    if checksum_valid:
        score += 0.25
        inputs.append(
            "SHA-256 checksum recorded at intake "
            f"({checksum[:16]}…), binding the stored artifact to the upload record."
        )
    else:
        missing.append("No valid 64-character SHA-256 checksum is recorded.")
    if file_present:
        score += 0.25
        inputs.append("The stored file was found in the upload volume.")
    else:
        missing.append("The stored file could not be found in the upload volume.")
    if size_matches:
        score += 0.20
        inputs.append(
            f"The stored file size matches the recorded {doc.file_size} byte(s)."
        )
    elif file_present:
        missing.append(
            "The stored file size does not match the recorded "
            f"{doc.file_size} byte(s) (found {actual_size})."
        )
    if doc.status == "processed":
        score += 0.15
        inputs.append("The document is marked as successfully processed.")
    elif doc.status == "error":
        missing.append(f"The document is in the '{doc.status}' state: {doc.error_message or 'no reason recorded'}.")
    else:
        missing.append(f"The document status is '{doc.status}', not processed.")
    if content_available:
        score += 0.15
        inputs.append("Extracted text is available for inspection.")
    else:
        missing.append("No extracted text is available.")

    if not checksum_valid and not file_present and not content_available:
        return _factor(
            "authenticity",
            status="unknown",
            score=None,
            summary="No stored artifact or intake record is available to check.",
            explanation=(
                "Source authenticity cannot be assessed because there is no "
                "checksum, no stored file and no extracted content."
            ),
            inputs=inputs,
            missing=missing,
        )

    if doc.is_demo:
        score = min(score, 0.5)
        inputs.append("The document is marked as demonstration data.")
        warnings.append(
            "Demonstration data: the file is synthetic and cannot establish the "
            "authenticity of a real-world source."
        )

    status = "recorded" if score >= 0.70 and not doc.is_demo else "partial"
    summary = (
        "Stored artifact matches the intake record."
        if status == "recorded"
        else "Only some authenticity checks could be completed."
    )
    explanation = (
        "These checks establish that the stored artifact is internally consistent "
        "with the intake record (checksum, file presence, size, processing). They "
        "do not prove that the document's contents are true."
    )
    if doc.is_demo:
        explanation += (
            " Demonstration documents are synthetic samples, so real-world "
            "authenticity is not assessable."
        )
    return _factor(
        "authenticity",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )


def _author_factor(
    metadata: dict,
    meta_out: dict,
    *,
    is_demo: bool,
    warnings: list[str],
) -> dict:
    author = meta_out["author"]
    organization = meta_out["organization"]
    signature = meta_out["signature"]

    inputs: list[str] = []
    missing: list[str] = []
    if author:
        inputs.append(f"Author/creator recorded: {author}.")
    else:
        missing.append("No author or creator is recorded in the source metadata.")
    if organization:
        inputs.append(f"Organization/publisher recorded: {organization}.")
    else:
        missing.append("No organization or publisher is recorded in the source metadata.")
    if signature:
        inputs.append(f"Signature/approval field recorded: {signature} (not verified).")

    if not author and not organization:
        return _factor(
            "author",
            status="unknown",
            score=None,
            summary="Author and organization are not recorded.",
            explanation=(
                "No author or organization value exists in the stored source "
                "metadata. NeuroSync does not infer an author from the filename or "
                "the document text."
            ),
            inputs=inputs,
            missing=missing,
        )

    score = 0.60 if (author and organization) else 0.45
    if signature:
        score += 0.10
    if is_demo:
        score = min(score, 0.6)
        inputs.append("The recorded identity is a demonstration placeholder.")
    status = "recorded" if author and organization else "partial"
    summary = (
        f"{author or 'Unnamed creator'} — {organization}"
        if author and organization
        else (author or organization or "Recorded identity")
    )
    explanation = (
        "The value(s) above are reproduced verbatim from source metadata. "
        "NeuroSync cannot verify that the named person or organization actually "
        "produced the document."
    )
    return _factor(
        "author",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )


def _publication_date_factor(
    doc: Document,
    meta_out: dict,
    *,
    warnings: list[str],
) -> dict:
    parsed, iso_value, precision, raw = _date_parts(meta_out.get("publication_date_raw"))
    inputs: list[str] = []
    missing: list[str] = []

    if raw:
        inputs.append(f"Publication date recorded in metadata: {raw}.")
    if parsed is not None and iso_value:
        inputs.append(f"Interpreted as {iso_value} ({precision} precision).")
    if doc.uploaded_at:
        inputs.append(
            "Recorded upload time: "
            f"{doc.uploaded_at.isoformat()} (not used as a publication date)."
        )

    if parsed is None:
        if raw:
            missing.append(
                f"The recorded publication date '{raw}' could not be parsed, so it "
                "was not interpreted or guessed."
            )
        else:
            missing.append(
                "No publication date is recorded in the source metadata; the "
                "upload time is not a publication date."
            )
        return _factor(
            "publication_date",
            status="unknown",
            score=None,
            summary="No usable publication date is recorded.",
            explanation=(
                "A publication date must be recorded in the source metadata. "
                "NeuroSync deliberately does not substitute the upload timestamp, "
                "which only records when the file arrived."
            ),
            inputs=inputs,
            missing=missing,
        )

    today = datetime.now(timezone.utc).date()
    score = 0.80
    status = "recorded"
    summary = parsed.isoformat() if precision == "day" else f"{iso_value} ({precision} only)"
    if precision in ("month", "year"):
        score, status = 0.45, "partial"
        missing.append(
            f"Only {precision}-level precision is recorded; the exact day is unknown."
        )
    if parsed.year < 1900 or parsed > today.replace(year=today.year + 1):
        score, status = 0.30, "partial"
        warnings.append(
            f"The recorded publication date ({parsed.isoformat()}) is implausible "
            "and should be checked."
        )
        missing.append("The recorded publication date is outside a plausible range.")
    explanation = (
        "The date is reproduced from source metadata and interpreted without "
        "guessing. NeuroSync cannot independently verify that the stated date is "
        "correct."
    )
    return _factor(
        "publication_date",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )


def _evidence_quality_factor(
    doc: Document,
    ctx: SourceCredibilityContext,
    *,
    content_available: bool,
    char_count: int,
    claims: list[Claim],
    evidence: list[Evidence],
) -> dict:
    inputs: list[str] = []
    missing: list[str] = []

    if not content_available:
        return _factor(
            "evidence_quality",
            status="unknown",
            score=None,
            summary="No extracted content is available.",
            explanation=(
                "Evidence quality cannot be assessed because no text was "
                "extracted from this source."
            ),
            missing=["No extracted text is available."],
        )

    claim_count = len(claims)
    evidence_count = len(evidence)
    primary_types = {
        item.evidence_type
        for item in evidence
        if item.evidence_type in ("measurement", "calibration_record", "timestamp")
    }
    primary = 1.0 if primary_types else 0.0
    directness = (
        sum(float(item.directness) for item in evidence) / evidence_count
        if evidence_count
        else 0.0
    )
    confidence = (
        sum(float(item.confidence) for item in claims) / claim_count
        if claim_count
        else 0.0
    )
    content_factor = min(char_count / 2000.0, 1.0)
    claims_factor = min(claim_count / 3.0, 1.0)
    evidence_factor = min(evidence_count / 2.0, 1.0)

    score = (
        0.25 * content_factor
        + 0.20 * claims_factor
        + 0.15 * evidence_factor
        + 0.15 * primary
        + 0.15 * directness
        + 0.10 * confidence
    )

    inputs.append(f"Extracted text length: {char_count} character(s).")
    inputs.append(f"Structured claims extracted: {claim_count}.")
    inputs.append(f"Evidence rows linked to this source: {evidence_count}.")
    if primary_types:
        inputs.append(
            "Primary evidence types present: "
            + ", ".join(sorted(primary_types))
            + "."
        )
    else:
        missing.append(
            "No measurement, calibration-record or timestamp evidence is linked "
            "to this source."
        )
    if evidence_count:
        inputs.append(f"Mean recorded directness of linked evidence: {directness:.2f}.")
    else:
        missing.append("No evidence rows are linked to this source.")
    if claim_count:
        inputs.append(f"Mean extraction confidence of claims: {confidence:.2f}.")
    else:
        missing.append("No claims were extracted, so evidential content is limited.")

    if not claims and not evidence:
        return _factor(
            "evidence_quality",
            status="partial",
            score=score,
            summary="Text is present but no structured evidence was extracted.",
            explanation=(
                "The source contains extractable text, but no claims or evidence "
                "rows were derived from it. The indicator reflects content volume "
                "only and must not be read as a quality judgement on the document."
            ),
            inputs=inputs,
            missing=missing,
        )

    status = "recorded" if score >= 0.60 else "partial"
    summary = (
        f"{claim_count} claim(s) and {evidence_count} linked evidence row(s)"
    )
    explanation = (
        "This factor measures how much direct, structured evidence the source "
        "actually contributes to NeuroSync (content volume, extracted claims, "
        "linked evidence, primary evidence types and recorded directness). It does "
        "not certify the truth of that evidence."
    )
    return _factor(
        "evidence_quality",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )


def _traceability_factor(
    doc: Document,
    ctx: SourceCredibilityContext,
    *,
    content_available: bool,
    claims: list[Claim],
    evidence: list[Evidence],
) -> dict:
    checksum_valid = bool(re.fullmatch(r"[0-9a-fA-F]{64}", (doc.checksum or "").strip()))
    file_present, _ = ctx.file_state.get(doc.id, (False, None))
    page_map: list[dict] = []
    content = ctx.contents.get(doc.id)
    if content:
        try:
            parsed = json.loads(content.page_map or "[]")
            page_map = parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            page_map = []
    located_pages = sum(1 for entry in page_map if entry.get("page") is not None)
    offset_entries = sum(1 for entry in page_map if isinstance(entry.get("start"), int))

    claims_located = sum(
        1 for claim in claims if (claim.source_reference or claim.source_location)
    )
    evidence_located = sum(
        1 for item in evidence if (item.source_reference or item.source_location)
    )

    inputs: list[str] = []
    missing: list[str] = []
    score = 0.0

    if checksum_valid:
        score += 0.30
        inputs.append("SHA-256 checksum provides a stable content identifier.")
    else:
        missing.append("No valid SHA-256 checksum is recorded.")
    if file_present:
        score += 0.20
        inputs.append("The stored file exists and can be retrieved.")
    else:
        missing.append("The stored file is not available for retrieval.")
    if content_available:
        score += 0.15
        inputs.append("Extracted text is stored in the document-content record.")
    else:
        missing.append("No extracted text is available to locate quotations.")
    if located_pages or offset_entries:
        score += 0.10
        inputs.append(
            f"Page map contains {located_pages} page number(s) and "
            f"{offset_entries} character-offset entries."
        )
    else:
        missing.append("No page numbers or character offsets are recorded.")
    if claims:
        ratio = claims_located / len(claims)
        score += 0.15 * ratio
        inputs.append(
            f"{claims_located}/{len(claims)} extracted claim(s) record a source "
            "reference or location."
        )
        if claims_located < len(claims):
            missing.append(
                f"{len(claims) - claims_located} extracted claim(s) have no recorded "
                "source reference or location."
            )
    else:
        missing.append("No extracted claims exist to trace back to the text.")
    if evidence:
        ratio = evidence_located / len(evidence)
        score += 0.10 * ratio
        inputs.append(
            f"{evidence_located}/{len(evidence)} linked evidence row(s) record a "
            "source location or reference."
        )
        if evidence_located < len(evidence):
            missing.append(
                f"{len(evidence) - evidence_located} evidence row(s) have no "
                "recorded source reference or location."
            )
    else:
        missing.append("No evidence rows are linked to this source.")

    if not checksum_valid and not file_present and not content_available and not claims:
        return _factor(
            "traceability",
            status="unknown",
            score=None,
            summary="Nothing stored can be traced back to a retrievable artifact.",
            explanation=(
                "The source has no checksum, no retrievable file, no content and "
                "no claims, so traceability cannot be assessed."
            ),
            inputs=inputs,
            missing=missing,
        )

    status = "recorded" if score >= 0.60 else "partial"
    summary = (
        "Every stored element has a traceable reference."
        if status == "recorded" and not missing
        else f"{len(missing)} traceability gap(s) recorded."
    )
    explanation = (
        "Traceability records whether the source and each derived item can be "
        "found again: checksum, stored file, extracted content, page/character "
        "locations and per-record source references. It does not verify the "
        "source's external origin."
    )
    return _factor(
        "traceability",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )


def _example(
    *,
    relation: str,
    claim: Claim,
    item: dict,
) -> dict:
    source = item.get("source") or {}
    return {
        "relation": relation,
        "claim_id": claim.id,
        "claim_text": (claim.claim_text or "")[:500],
        "other_document_id": source.get("document_id"),
        "other_document_filename": source.get("document_filename"),
        "text": (item.get("text") or "")[:500],
        "reason": item.get("reason") or "",
        "independence": item.get("independence") or "",
    }


def _consistency_factor(
    db: Session,
    doc: Document,
    ctx: SourceCredibilityContext,
    claims: list[Claim],
    *,
    warnings: list[str],
) -> tuple[dict, dict]:
    if not claims:
        factor = _factor(
            "consistency",
            status="not_applicable",
            score=None,
            summary="No extracted claims to compare.",
            explanation=(
                "Consistency can only be checked for claims extracted from this "
                "source. None were extracted, so the factor is not applicable."
            ),
            missing=["No claims were extracted from this source."],
        )
        return factor, {
            "status": "not_applicable",
            "score": None,
            "claims_checked": 0,
            "supported": 0,
            "contradicted": 0,
            "partially_supported": 0,
            "unverified": 0,
            "explanation": "No extracted claims are available for comparison.",
            "supporting": [],
            "contradicting": [],
        }

    counts = {
        "supported": 0,
        "contradicted": 0,
        "partially_supported": 0,
        "unverified": 0,
    }
    supporting: list[dict] = []
    contradicting: list[dict] = []
    seen_support: set[tuple] = set()
    seen_contradict: set[tuple] = set()
    other_docs: set[str] = set()

    for claim in claims:
        result = verify_claim(db, claim, index=ctx.verification_index)
        verdict = result.get("verdict")
        if verdict in counts:
            counts[verdict] += 1

        for item in result.get("supporting_evidence", []):
            source = item.get("source") or {}
            other_id = source.get("document_id")
            if other_id is None or other_id == doc.id:
                continue
            if item.get("independence") not in ("independent", "user_supplied"):
                continue
            key = (other_id, (item.get("text") or "")[:120])
            if key in seen_support or len(supporting) >= _MAX_EXAMPLES:
                continue
            seen_support.add(key)
            supporting.append(_example(relation="supporting", claim=claim, item=item))
            other_docs.add(source.get("document_filename") or f"document #{other_id}")

        for item in result.get("contradicting_evidence", []):
            source = item.get("source") or {}
            other_id = source.get("document_id")
            if other_id is None or other_id == doc.id:
                continue
            if item.get("independence") not in ("independent", "user_supplied"):
                continue
            key = (other_id, (item.get("text") or "")[:120])
            if key in seen_contradict or len(contradicting) >= _MAX_EXAMPLES:
                continue
            seen_contradict.add(key)
            contradicting.append(_example(relation="contradicting", claim=claim, item=item))
            other_docs.add(source.get("document_filename") or f"document #{other_id}")

    comparisons = counts["supported"] + counts["contradicted"] + counts["partially_supported"]
    detail = {
        "claims_checked": len(claims),
        "supported": counts["supported"],
        "contradicted": counts["contradicted"],
        "partially_supported": counts["partially_supported"],
        "unverified": counts["unverified"],
        "supporting": supporting,
        "contradicting": contradicting,
    }

    if comparisons == 0:
        factor = _factor(
            "consistency",
            status="unknown",
            score=None,
            summary="No claim could be compared with another source.",
            explanation=(
                f"All {len(claims)} extracted claim(s) are unverified against other "
                "documents: no other source addresses the same fact. Absence of "
                "comparison is reported as unknown, not as inconsistency."
            ),
            inputs=[
                f"{len(claims)} extracted claim(s) checked against the other stored documents.",
                "No comparable claim or sentence was found in another source.",
            ],
            missing=[
                "No other source addresses the same fact, so consistency cannot be assessed.",
            ],
        )
        detail["status"] = "unknown"
        detail["score"] = None
        detail["explanation"] = factor["explanation"]
        return factor, detail

    if counts["contradicted"] and counts["supported"] == 0:
        status, score = "inconsistent", 0.15
        summary = f"{counts['contradicted']} claim(s) contradicted by other sources."
        warnings.append(
            "Claims from this source are contradicted by other available sources; "
            "review the disagreement before relying on it."
        )
    elif counts["contradicted"]:
        status, score = "mixed", 0.40
        summary = (
            f"{counts['supported']} claim(s) agree and {counts['contradicted']} "
            "disagree with other sources."
        )
        warnings.append(
            "This source both agrees and disagrees with other available sources."
        )
    elif counts["supported"]:
        status = "consistent"
        score = min(0.90, 0.75 + 0.05 * min(counts["supported"], 3))
        summary = f"{counts['supported']} claim(s) corroborated by other sources."
    else:
        status, score = "mixed", 0.45
        summary = f"{counts['partially_supported']} claim(s) only partially agree."

    sources = ", ".join(sorted(other_docs)) or "other stored documents"
    explanation = (
        f"{len(claims)} claim(s) from this source were compared with {sources}. "
        f"{counts['supported']} were supported, {counts['contradicted']} "
        f"contradicted, {counts['partially_supported']} partially supported and "
        f"{counts['unverified']} could not be compared. Same-source restatements "
        "are never counted as independent agreement."
    )
    inputs = [
        f"{len(claims)} extracted claim(s) checked.",
        f"{comparisons} claim(s) had at least one comparable item in another source.",
        f"Other sources involved: {sources}.",
    ]
    missing = []
    if counts["unverified"]:
        missing.append(
            f"{counts['unverified']} claim(s) could not be compared with another source."
        )
    factor = _factor(
        "consistency",
        status=status,
        score=score,
        summary=summary,
        explanation=explanation,
        inputs=inputs,
        missing=missing,
    )
    detail.update({"status": status, "score": round(_clamp(score), 3), "explanation": explanation})
    return factor, detail


# -------------------------------------------------------------------- aggregate
def _aggregate(factors: dict[str, dict]) -> tuple[str, float | None, float]:
    known_weight = sum(
        FACTOR_WEIGHTS[key]
        for key, factor in factors.items()
        if factor.get("score") is not None
    )
    total_weight = sum(FACTOR_WEIGHTS.values())
    coverage = known_weight / total_weight if total_weight else 0.0

    if known_weight < MIN_ASSESSABLE_WEIGHT:
        return "unverifiable", None, round(coverage, 3)

    weighted = sum(
        FACTOR_WEIGHTS[key] * float(factor["score"])
        for key, factor in factors.items()
        if factor.get("score") is not None
    )
    overall = round(_clamp(weighted / known_weight), 3)
    if overall >= 0.70 and coverage >= MIN_COVERAGE_FOR_WELL_DOCUMENTED:
        label = "well_documented"
    elif overall >= 0.45:
        label = "partially_documented"
    else:
        label = "limited_documentation"
    return label, overall, round(coverage, 3)


def _summary(
    label: str,
    factors: dict[str, dict],
    coverage: float,
    unknown_factors: list[str],
) -> str:
    if label == "unverifiable":
        return (
            "Insufficient stored information is available to assess this source. "
            "It is marked unverifiable rather than assigned a low score."
        )
    assessed = len([f for f in factors.values() if f.get("score") is not None])
    text = (
        f"{LEVEL_LABELS[label]}: {assessed}/{len(factors)} factors are assessable "
        f"({coverage:.0%} of the weighted checklist)."
    )
    if unknown_factors:
        names = ", ".join(FACTOR_LABELS[key].lower() for key in unknown_factors)
        text += f" Not assessable from stored information: {names}."
    return text


def _overall_explanation(
    label: str,
    overall: float | None,
    coverage: float,
    factors: dict[str, dict],
) -> str:
    if label == "unverifiable" or overall is None:
        return (
            "The aggregate is withheld because less than 40% of the weighted "
            "checklist has usable inputs. No missing factor is treated as a zero. "
            "The source is therefore unverifiable from the records currently stored."
        )
    unknown = [
        FACTOR_LABELS[key].lower()
        for key, factor in factors.items()
        if factor.get("score") is None
    ]
    text = (
        f"Overall indicator {overall:.2f} is the weighted mean of the assessed "
        f"factors only ({coverage:.0%} coverage). "
    )
    if unknown:
        text += (
            "The following factors were excluded rather than scored as zero: "
            + ", ".join(unknown)
            + ". "
        )
    text += (
        "This is a documentation/provenance indicator derived from stored fields, "
        "not a truthfulness rating."
    )
    return text


# ------------------------------------------------------------------- public API
def assess_source(
    db: Session,
    doc: Document,
    *,
    context: SourceCredibilityContext | None = None,
) -> dict:
    """Return an inspectable credibility assessment for one stored source."""
    ctx = context or build_context(db, [doc])
    content = ctx.contents.get(doc.id)
    text = (content.text if content else "") or ""
    content_available = bool(text.strip())
    char_count = len(text) if content_available else (content.char_count if content else 0)
    claims = ctx.claims_by_doc.get(doc.id, [])
    evidence = ctx.evidence_by_doc.get(doc.id, [])

    metadata = _parse_metadata(doc.source_metadata)
    author, _ = _metadata_value(metadata, _METADATA_ALIASES["author"])
    organization, _ = _metadata_value(metadata, _METADATA_ALIASES["organization"])
    publication_raw, publication_key = _metadata_value(
        metadata, _METADATA_ALIASES["publication_date"]
    )
    source_type, _ = _metadata_value(metadata, _METADATA_ALIASES["source_type"])
    version, _ = _metadata_value(metadata, _METADATA_ALIASES["version"])
    signature, _ = _metadata_value(metadata, _METADATA_ALIASES["signature"])

    identifiers: list[str] = []
    for key, value in metadata.items():
        if _normalise_key(key) in _METADATA_ALIASES["identifier"]:
            text_value = _stringify(value)
            if text_value and text_value not in identifiers:
                identifiers.append(text_value)

    fields: dict[str, str] = {}
    if author:
        fields["author"] = author
    if organization:
        fields["organization"] = organization
    if publication_raw:
        fields["publication_date"] = publication_raw
        if publication_key:
            fields[f"publication_date_source_key"] = publication_key
    if source_type:
        fields["source_type"] = source_type
    if version:
        fields["version"] = version
    if signature:
        fields["signature"] = signature
    if identifiers:
        fields["identifiers"] = ", ".join(identifiers)

    meta_out = {
        "author": author,
        "organization": organization,
        "publication_date": publication_raw,
        "publication_date_raw": publication_raw,
        "publication_date_precision": None,
        "source_type": source_type,
        "identifiers": identifiers,
        "version": version,
        "signature": signature,
        "fields": fields,
        "raw": metadata,
    }

    warnings: list[str] = []
    missing: list[str] = []

    authenticity = _authenticity_factor(
        doc, ctx, content_available=content_available, warnings=warnings
    )
    author_factor = _author_factor(
        metadata, meta_out, is_demo=bool(doc.is_demo), warnings=warnings
    )
    date_factor = _publication_date_factor(doc, meta_out, warnings=warnings)
    quality = _evidence_quality_factor(
        doc,
        ctx,
        content_available=content_available,
        char_count=char_count,
        claims=claims,
        evidence=evidence,
    )
    traceability = _traceability_factor(
        doc, ctx, content_available=content_available, claims=claims, evidence=evidence
    )
    consistency, consistency_detail = _consistency_factor(
        db, doc, ctx, claims, warnings=warnings
    )

    factors = {
        "authenticity": authenticity,
        "author": author_factor,
        "publication_date": date_factor,
        "evidence_quality": quality,
        "traceability": traceability,
        "consistency": consistency,
    }

    # The interpreted date value is exposed separately from the raw metadata.
    parsed, iso_value, precision, _ = _date_parts(publication_raw)
    meta_out["publication_date"] = iso_value or publication_raw
    meta_out["publication_date_precision"] = precision or None

    label, overall, coverage = _aggregate(factors)
    unknown_factors = [
        key for key, factor in factors.items() if factor.get("score") is None
    ]
    for factor in factors.values():
        for item in factor.get("missing", []):
            if item not in missing:
                missing.append(item)

    duplicate_count = ctx.duplicate_checksums.get((doc.checksum or "").strip(), 0)
    if duplicate_count > 1:
        warnings.append(
            f"{duplicate_count} stored documents share this checksum; confirm which "
            "copy is authoritative."
        )
    if doc.is_demo:
        warnings.append(
            "This source is demonstration data. Recorded identities and dates are "
            "sample placeholders, not real credentials."
        )
    if not author and not organization:
        warnings.append(
            "The source has no recorded author or organization; it is anonymous to "
            "NeuroSync."
        )
    if not publication_raw:
        warnings.append(
            "The source has no recorded publication date; its currency cannot be "
            "established."
        )

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "status": doc.status,
        "is_demo": bool(doc.is_demo),
        "uploaded_at": doc.uploaded_at,
        "processed_at": doc.processed_at,
        "checksum": doc.checksum or "",
        "stored_file_present": ctx.file_state.get(doc.id, (False, None))[0],
        "stored_file_size": ctx.file_state.get(doc.id, (False, None))[1],
        "content_available": content_available,
        "char_count": char_count,
        "claim_count": len(claims),
        "observation_count": ctx.observations_by_doc.get(doc.id, 0),
        "evidence_count": len(evidence),
        "source_metadata": meta_out,
        "overall_label": label,
        "overall_label_display": LEVEL_LABELS[label],
        "overall_score": overall,
        "coverage": coverage,
        "summary": _summary(label, factors, coverage, unknown_factors),
        "explanation": _overall_explanation(label, overall, coverage, factors),
        "factors": factors,
        "unknown_factors": unknown_factors,
        "warnings": warnings,
        "missing_information": missing,
        "consistency": consistency_detail,
        "methodology": METHODOLOGY,
        "caveat": CAVEAT,
        "analyzed_at": datetime.now(timezone.utc),
    }


def assess_many(
    db: Session,
    documents: list[Document],
    *,
    context: SourceCredibilityContext | None = None,
) -> list[dict]:
    if not documents:
        return []
    ctx = context or build_context(db, documents)
    return [assess_source(db, doc, context=ctx) for doc in documents]


def credibility_counts(items: list[dict]) -> dict[str, int]:
    counts = {level: 0 for level in LEVEL_LABELS}
    for item in items:
        label = item.get("overall_label")
        if label in counts:
            counts[label] += 1
    counts["unknown_author"] = sum(
        1 for item in items if not (item.get("source_metadata") or {}).get("author")
    )
    counts["unknown_organization"] = sum(
        1 for item in items if not (item.get("source_metadata") or {}).get("organization")
    )
    counts["unknown_publication_date"] = sum(
        1 for item in items if not (item.get("source_metadata") or {}).get("publication_date")
    )
    counts["with_consistency_conflicts"] = sum(
        1
        for item in items
        if (item.get("consistency") or {}).get("contradicted", 0) > 0
    )
    counts["demonstration_sources"] = sum(1 for item in items if item.get("is_demo"))
    return counts


def documents_for_investigation(investigation: Investigation) -> list[Document]:
    """The investigation's own documents, ordered deterministically by id."""
    return sorted(investigation.documents, key=lambda doc: doc.id)
