"""Document service: validation, safe storage and text extraction.

Supported formats: PDF (PyMuPDF), DOCX (python-docx), TXT. Uploaded files are
never executed. Content is treated as untrusted data.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings, UPLOAD_DIR
from ..models import Claim, Conflict, Document, DocumentContent, Observation

logger = logging.getLogger("neurosync.documents")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "application/octet-stream",
}

MAX_BYTES = settings.max_upload_mb * 1024 * 1024
# Uploads are streamed to disk in this chunk size, so peak Python memory is
# bounded by the chunk (not the whole file) regardless of upload size.
_READ_CHUNK_BYTES = 1024 * 1024


class DocumentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base[:200] or "document"


def _validate_extension(filename: str, content_type: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentError(f"Unsupported file type '{ext or 'unknown'}'. Allowed: PDF, DOCX, TXT.", 415)
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise DocumentError(f"Unsupported content type '{content_type}'.", 415)


def validate_upload(filename: str, content_type: str, size: int) -> None:
    _validate_extension(filename, content_type)
    if size > MAX_BYTES:
        raise DocumentError(
            f"File exceeds maximum size of {settings.max_upload_mb} MB.", 413
        )
    if size == 0:
        raise DocumentError("File is empty.", 400)


def _extract_pdf(path: Path) -> tuple[str, list[dict]]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("PDF support is unavailable (PyMuPDF not installed).", 500) from exc
    text_parts: list[str] = []
    page_map: list[dict] = []
    # ``start`` is the character offset of the page inside the joined text, so
    # downstream features (fact verification) can report an exact page for a
    # quoted claim instead of guessing from the filename alone.
    offset = 0
    started = False
    try:
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, start=1):
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    page_map.append({"page": i, "start": offset})
                    text_parts.append(page_text)
                    offset += len(page_text) + 1  # + the "\n" used to join pages
            started = True
    except Exception as exc:  # pragma: no cover - corrupt PDF
        raise DocumentError(f"Could not read PDF: {type(exc).__name__}", 422) from exc
    if not started:  # pragma: no cover
        raise DocumentError("Could not open PDF.", 422)
    return "\n".join(text_parts).strip(), page_map


def _extract_docx(path: Path) -> tuple[str, list[dict]]:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover
        raise DocumentError("DOCX support is unavailable (python-docx not installed).", 500) from exc
    try:
        document = docx.Document(str(path))
        paragraphs = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    except Exception as exc:  # pragma: no cover
        raise DocumentError(f"Could not read DOCX: {type(exc).__name__}", 422) from exc
    return "\n".join(paragraphs).strip(), [{"page": None, "start": 0}]


def _extract_txt(path: Path) -> tuple[str, list[dict]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        raise DocumentError(f"Could not read text file: {type(exc).__name__}", 422) from exc
    return text.strip(), [{"page": None, "start": 0}]


def extract_text(path: Path, file_type: str) -> tuple[str, list[dict]]:
    ft = file_type.lower()
    if ft == "pdf":
        return _extract_pdf(path)
    if ft == "docx":
        return _extract_docx(path)
    return _extract_txt(path)


def save_upload(file: UploadFile, is_demo: bool = False, declared_type: str | None = None) -> Document:
    """Persist an uploaded file to disk and return an uncommitted Document.

    The file is streamed to disk in fixed-size chunks (never held whole in
    memory) and aborted as soon as it exceeds ``max_upload_mb``, so an oversized
    upload cannot exhaust memory before the size check. The SHA-256 checksum is
    computed incrementally over the same chunks.
    """
    filename = file.filename or "upload"
    file_type = (declared_type or Path(filename).suffix.lstrip(".")).lower()
    content_type = file.content_type or ""
    _validate_extension(filename, content_type)

    checksum = hashlib.sha256()
    stored = f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    dest = UPLOAD_DIR / stored
    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = file.file.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DocumentError(
                        f"File exceeds maximum size of {settings.max_upload_mb} MB.", 413
                    )
                checksum.update(chunk)
                out.write(chunk)
        if size == 0:
            raise DocumentError("File is empty.", 400)
    except BaseException:
        # Never leave a partial file behind when validation or the read fails.
        dest.unlink(missing_ok=True)
        raise

    return Document(
        filename=safe_filename(filename),
        stored_filename=stored,
        file_type=file_type,
        content_type=content_type,
        file_size=size,
        checksum=checksum.hexdigest(),
        status="pending",
        is_demo=1 if is_demo else 0,
    )


def discard_uncommitted(document: Document) -> None:
    """Delete the on-disk file for a Document that was never committed.

    Used to clean up after a duplicate upload or a failed commit so rejected
    uploads do not accumulate as orphaned files on the upload volume.
    """
    if not document.stored_filename:
        return
    try:
        (UPLOAD_DIR / document.stored_filename).unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best-effort cleanup
        logger.warning("Could not remove orphaned upload %s", document.stored_filename)


def create_document_from_text(
    db: Session,
    filename: str,
    text: str,
    is_demo: bool = False,
    source_metadata: dict | None = None,
) -> Document:
    """Create a document directly from text (used by the demo scenario)."""
    raw = text.encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    stored = f"demo_{uuid.uuid4().hex}_{safe_filename(filename)}"
    dest = UPLOAD_DIR / stored
    dest.write_text(text, encoding="utf-8")
    doc = Document(
        filename=safe_filename(filename),
        stored_filename=stored,
        file_type=Path(filename).suffix.lstrip(".").lower() or "txt",
        content_type="text/plain",
        file_size=len(raw),
        checksum=checksum,
        status="pending",
        is_demo=1 if is_demo else 0,
        source_metadata=json.dumps(source_metadata or {}),
    )
    db.add(doc)
    db.flush()
    return doc


def find_duplicate(db: Session, checksum: str) -> Document | None:
    return db.execute(select(Document).where(Document.checksum == checksum)).scalars().first()


def get_document(db: Session, document_id: int) -> Document | None:
    return db.get(Document, document_id)


def list_documents(db: Session) -> list[Document]:
    return list(db.execute(select(Document).order_by(Document.uploaded_at.desc())).scalars())


def extract_document_content(db: Session, document: Document) -> tuple[int, int]:
    """Deterministically extract observations and claims for a document.

    Idempotent: does nothing if the document already has claims. Returns
    (observation_count, claim_count). Shared by the upload pipeline and the
    Evidence Collector agent so both stay consistent.
    """
    from .claim_extraction import extract_claims, extract_observations

    existing = db.execute(select(Claim).where(Claim.document_id == document.id)).scalars().first()
    if existing is not None:
        return (0, 0)

    content = db.execute(
        select(DocumentContent).where(DocumentContent.document_id == document.id)
    ).scalars().first()
    if content is None or not content.text.strip():
        return (0, 0)

    ref = document.filename
    obs_count = 0
    for obs in extract_observations(content.text, ref):
        db.add(
            Observation(
                document_id=document.id,
                text=obs["text"],
                observation_type=obs["observation_type"],
                source_location=ref,
                extraction_method="rule_based",
            )
        )
        obs_count += 1

    claim_count = 0
    for claim in extract_claims(content.text, ref):
        db.add(
            Claim(
                document_id=document.id,
                claim_text=claim.claim_text,
                subject=claim.subject,
                predicate=claim.predicate,
                object_value=claim.object_value,
                numeric_value=claim.numeric_value,
                unit=claim.unit,
                polarity=claim.polarity,
                claim_type=claim.claim_type,
                timestamp_value=claim.timestamp_value,
                source_reference=ref,
                source_location=ref,
                confidence=claim.confidence,
            )
        )
        claim_count += 1
    db.flush()
    return (obs_count, claim_count)


def document_has_llm_claims(db: Session, document_id: int) -> bool:
    """True when the document already has at least one LLM-suggested claim."""
    for claim in db.execute(select(Claim).where(Claim.document_id == document_id)).scalars():
        try:
            meta = json.loads(claim.meta or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("extraction_method") == "llm":
            return True
    return False


def document_llm_attempted(db: Session, document_id: int) -> bool:
    """True when LLM claim augmentation has already been attempted for a document.

    The attempt is recorded in the audit trail (not via an added column, which
    would require a migration). This prevents the Evidence Collector from
    re-attempting augmentation forever when the model legitimately returns no
    additional claims.

    The lookup is keyed on the indexed ``(entity_type, action, entity_id)``
    columns rather than scanning every audit row and parsing its JSON detail.
    """
    from ..models import AuditEvent

    row = db.execute(
        select(AuditEvent.id)
        .where(
            AuditEvent.entity_type == "document",
            AuditEvent.action == "llm_augmented",
            AuditEvent.entity_id == document_id,
        )
        .limit(1)
    ).first()
    return row is not None


def augment_document_with_llm(
    db: Session,
    document: Document,
    investigation_id: int | None = None,
    actor: str = "llm",
) -> int:
    """Add LLM-suggested claims, but only ones that are grounded in the text.

    The model can never introduce a claim whose supporting quote is absent from
    the document. Invalid or ungrounded suggestions are silently dropped. An
    attempt is always recorded (even when nothing is added) so the caller does
    not retry indefinitely. Returns the number of claims actually added.
    """
    from . import audit_service
    from .claim_extraction import _find_subject, _parse_time
    from .llm_service import is_grounded, llm_service

    content = db.execute(
        select(DocumentContent).where(DocumentContent.document_id == document.id)
    ).scalars().first()
    if content is None or not content.text.strip():
        return 0

    suggestions = llm_service.extract_claims(content.text)
    existing = {
        (c.claim_text or "").strip().lower()
        for c in db.execute(select(Claim).where(Claim.document_id == document.id)).scalars()
    }
    allowed_types = {"measurement", "state", "event", "statement"}
    ref = document.filename
    added = 0
    for s in (suggestions or []):
        quote = (s.evidence_quote or s.claim_text or "").strip()
        if not quote or not is_grounded(quote, [content.text]):
            continue
        text = (s.claim_text or quote).strip()
        if not text or text.lower() in existing:
            continue
        subject = (s.subject or "").strip() or _find_subject(text.lower()) or "value"
        claim_type = s.claim_type if s.claim_type in allowed_types else "statement"
        db.add(
            Claim(
                document_id=document.id,
                claim_text=text,
                subject=subject,
                predicate=(s.predicate or "").strip(),
                object_value=(s.object_value or "").strip(),
                claim_type=claim_type,
                timestamp_value=_parse_time(text),
                source_reference=ref,
                source_location=ref,
                confidence=0.5,
                meta=json.dumps(
                    {
                        "extraction_method": "llm",
                        "ai_suggested": True,
                        "evidence_quote": quote,
                    }
                ),
            )
        )
        existing.add(text.lower())
        added += 1
    db.flush()
    audit_service.record(
        db,
        entity_type="document",
        entity_id=document.id,
        action="llm_augmented",
        actor=actor,
        investigation_id=investigation_id,
        summary=(
            f"LLM claim augmentation for '{document.filename}': "
            f"{added} grounded claim(s) added from {len(suggestions or [])} suggestion(s)."
        ),
        detail={"document_id": document.id, "claims_added": added, "suggested": len(suggestions or [])},
    )
    if added:
        logger.info("LLM added %s grounded claim(s) to document %s", added, document.id)
    return added


def process_document(db: Session, document: Document, extract: bool = True) -> Document:
    """Extract text and store it. Sets status to processed or error.

    When ``extract`` is True (the default used for user uploads) claims and
    observations are produced immediately so the dashboard shows real counts.
    """
    document.status = "processing"
    db.flush()
    try:
        path = UPLOAD_DIR / document.stored_filename
        text, page_map = extract_text(path, document.file_type)
        if not text.strip():
            document.status = "error"
            document.error_message = "No extractable text found (the file may be a scanned image)."
            db.commit()
            return document
        if len(text) > settings.max_extracted_chars:
            # Defends against decompression/zip-bomb documents whose extracted
            # text far exceeds the (compressed) upload size limit.
            document.status = "error"
            document.error_message = (
                f"Extracted text exceeds the {settings.max_extracted_chars} character limit."
            )
            db.commit()
            return document
        content = db.execute(
            select(DocumentContent).where(DocumentContent.document_id == document.id)
        ).scalars().first()
        if content is None:
            content = DocumentContent(document_id=document.id)
            db.add(content)
        content.text = text
        content.page_map = json.dumps(page_map)
        content.char_count = len(text)
        document.status = "processed"
        document.error_message = ""
        from datetime import datetime, timezone

        document.processed_at = datetime.now(timezone.utc)
        db.flush()  # autoflush is disabled; make the content row visible to extraction
        if extract:
            extract_document_content(db, document)
        db.commit()
    except DocumentError as exc:
        document.status = "error"
        document.error_message = exc.message
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected document processing error")
        document.status = "error"
        document.error_message = f"Unexpected processing error: {type(exc).__name__}"
        db.commit()
    return document


def _conflict_count_for_document(db: Session, document_id: int) -> int:
    claim_id_subq = select(Claim.id).where(Claim.document_id == document_id).scalar_subquery()
    return int(
        db.execute(
            select(func.count())
            .select_from(Conflict)
            .where(
                Conflict.claim_a_id.in_(claim_id_subq)
                | Conflict.claim_b_id.in_(claim_id_subq)
            )
        ).scalar()
        or 0
    )


def document_stats(db: Session, document_id: int) -> dict[str, int]:
    """Counts for a single document, computed in the database (no row loads)."""
    claim_count = int(
        db.execute(
            select(func.count()).select_from(Claim).where(Claim.document_id == document_id)
        ).scalar()
        or 0
    )
    obs_count = int(
        db.execute(
            select(func.count()).select_from(Observation).where(Observation.document_id == document_id)
        ).scalar()
        or 0
    )
    return {
        "claim_count": claim_count,
        "observation_count": obs_count,
        "conflict_count": _conflict_count_for_document(db, document_id),
    }


def document_stats_map(db: Session, document_ids: list[int]) -> dict[int, dict[str, int]]:
    """Counts for many documents in a constant number of queries.

    Used by the document list so a page of N documents is assembled with a
    handful of grouped queries instead of ~4 queries per document.
    """
    ids = list(document_ids)
    stats: dict[int, dict[str, int]] = {
        i: {"claim_count": 0, "observation_count": 0, "conflict_count": 0} for i in ids
    }
    if not ids:
        return stats

    claim_counts = dict(
        db.execute(
            select(Claim.document_id, func.count())
            .where(Claim.document_id.in_(ids))
            .group_by(Claim.document_id)
        ).all()
    )
    obs_counts = dict(
        db.execute(
            select(Observation.document_id, func.count())
            .where(Observation.document_id.in_(ids))
            .group_by(Observation.document_id)
        ).all()
    )

    claim_rows = db.execute(
        select(Claim.id, Claim.document_id).where(Claim.document_id.in_(ids))
    ).all()
    claim_to_doc = {claim_id: doc_id for claim_id, doc_id in claim_rows}
    all_claim_ids = list(claim_to_doc)
    if all_claim_ids:
        conflict_rows = db.execute(
            select(Conflict.claim_a_id, Conflict.claim_b_id).where(
                Conflict.claim_a_id.in_(all_claim_ids) | Conflict.claim_b_id.in_(all_claim_ids)
            )
        ).all()
        for claim_a, claim_b in conflict_rows:
            touched: set[int] = set()
            for claim_id in (claim_a, claim_b):
                doc_id = claim_to_doc.get(claim_id)
                if doc_id is not None and doc_id not in touched:
                    touched.add(doc_id)
                    stats[doc_id]["conflict_count"] += 1

    for doc_id in ids:
        stats[doc_id]["claim_count"] = int(claim_counts.get(doc_id, 0))
        stats[doc_id]["observation_count"] = int(obs_counts.get(doc_id, 0))
    return stats


def delete_document(db: Session, document: Document) -> None:
    """Delete a document and its content file; cascade handles related rows."""
    path = UPLOAD_DIR / document.stored_filename
    try:
        if path.exists():
            path.unlink()
    except OSError:  # pragma: no cover
        logger.warning("Could not delete file %s", path)
    db.delete(document)
    db.commit()
