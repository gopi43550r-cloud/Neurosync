"""Document endpoints: upload, list, detail, delete, reprocess."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..schemas.common import MessageResponse, Page
from ..schemas.document import DocumentDetail, DocumentOut, DocumentUploadResponse
from ..services import document_service
from ..services.document_service import DocumentError
from ..services.serialization import document_to_detail, documents_to_out
from .pagination import paginate

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> list[DocumentUploadResponse]:
    results: list[DocumentUploadResponse] = []
    for file in files:
        try:
            doc = document_service.save_upload(file)
        except DocumentError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

        duplicate = document_service.find_duplicate(db, doc.checksum)
        if duplicate is not None:
            # The bytes were already streamed to disk; drop them so a repeated
            # upload does not accumulate orphaned files.
            document_service.discard_uncommitted(doc)
            results.append(
                DocumentUploadResponse(
                    id=duplicate.id,
                    filename=duplicate.filename,
                    status=duplicate.status,
                    message="Duplicate of an existing document; not uploaded again.",
                    duplicate=True,
                )
            )
            continue

        try:
            db.add(doc)
            db.commit()
        except Exception:
            db.rollback()
            document_service.discard_uncommitted(doc)
            raise
        db.refresh(doc)
        document_service.process_document(db, doc)
        stats = document_service.document_stats(db, doc.id)
        results.append(
            DocumentUploadResponse(
                id=doc.id,
                filename=doc.filename,
                status=doc.status,
                message=doc.error_message or "Uploaded and processed.",
                claim_count=stats["claim_count"],
                conflict_count=stats["conflict_count"],
            )
        )
    return results


@router.get("", response_model=Page[DocumentOut])
def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[DocumentOut]:
    stmt = select(Document).order_by(Document.uploaded_at.desc(), Document.id.desc())
    docs, total = paginate(db, stmt, page, page_size)
    return Page(
        items=documents_to_out(db, docs),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: int, db: Session = Depends(get_db)) -> DocumentDetail:
    doc = document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document_to_detail(db, doc)


@router.post("/{document_id}/reprocess", response_model=DocumentDetail)
def reprocess_document(document_id: int, db: Session = Depends(get_db)) -> DocumentDetail:
    doc = document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    document_service.process_document(db, doc)
    return document_to_detail(db, doc)


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    doc = document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    document_service.delete_document(db, doc)
    return MessageResponse(message=f"Document {document_id} deleted.")
