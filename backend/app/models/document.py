"""Document and document-content models.

Large extracted text is stored in a separate table so dashboard queries do not
need to load document bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf/docx/txt
    content_type: Mapped[str] = mapped_column(String(200), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[int] = mapped_column(Integer, default=0)
    source_metadata: Mapped[str] = mapped_column(Text, default="{}")  # JSON string
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    content: Mapped["DocumentContent"] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    observations: Mapped[list["Observation"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentContent(Base):
    __tablename__ = "document_contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, default="")
    page_map: Mapped[str] = mapped_column(Text, default="[]")  # JSON: [{"page":1,"start":0}]
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="content")
