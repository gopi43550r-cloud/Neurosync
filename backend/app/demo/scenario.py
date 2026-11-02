"""[DEMONSTRATION DATA]

A realistic sample scenario: "Industrial Equipment Diagnostic Investigation".

The three reports below are clearly labelled demonstration data. They are
loaded through the same document, extraction and investigation services used
for real uploads; nothing special is bypassed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Document
from ..schemas.investigation import InvestigationCreate
from ..services import document_service, investigation_service

DEMO_REPORTS = [
    {
        "filename": "Inspection_Report_A.txt",
        "text": (
            "[DEMONSTRATION DATA] Inspection Report A\n"
            "Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM."
        ),
        "metadata": {"report": "A", "inspector": "Inspector A", "is_demo": True},
    },
    {
        "filename": "Inspection_Report_B.txt",
        "text": (
            "[DEMONSTRATION DATA] Inspection Report B\n"
            "Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM."
        ),
        "metadata": {"report": "B", "inspector": "Inspector B", "is_demo": True},
    },
    {
        "filename": "Maintenance_Log_C.txt",
        "text": (
            "[DEMONSTRATION DATA] Maintenance Log C\n"
            "The temperature sensor was recalibrated at 10:30 AM."
        ),
        "metadata": {"report": "C", "technician": "Technician C", "is_demo": True},
    },
]

DEMO_NAME = "Machine M-17 Temperature Disagreement Investigation"
DEMO_QUESTION = (
    "Two inspection reports record different temperatures for machine M-17 at the same time "
    "(92°C vs 76°C). Can the disagreement be explained, and does the later sensor "
    "recalibration account for it?"
)


def load_demo(db: Session, auto_start: bool = False) -> tuple[list[Document], int]:
    """Create the demo documents and investigation. Returns (documents, investigation_id)."""
    documents: list[Document] = []
    for report in DEMO_REPORTS:
        doc = document_service.create_document_from_text(
            db,
            filename=report["filename"],
            text=report["text"],
            is_demo=True,
            source_metadata=report["metadata"],
        )
        # Demo documents are seeded as raw text only; the Evidence Collector
        # agent performs extraction during the investigation so the full agent
        # pipeline is demonstrated. All other services are identical to uploads.
        document_service.process_document(db, doc, extract=False)
        documents.append(doc)

    payload = InvestigationCreate(
        name=DEMO_NAME,
        research_question=DEMO_QUESTION,
        document_ids=[d.id for d in documents],
        iteration_limit=25,
        min_evidence_threshold=1,
        enable_llm=True,
    )
    investigation = investigation_service.create_investigation(db, payload, is_demo=True)
    if auto_start:
        investigation_service.start_investigation(db, investigation)
    return documents, investigation.id


def reset_demo(db: Session) -> int:
    """Delete all demo documents and demo investigations. Returns count removed.

    Investigations are removed before documents so that any association rows are
    cleaned up first; foreign-key cascades then remove their conclusions and
    blackboard rows.
    """
    removed = 0
    from ..models import Investigation

    for inv in db.query(Investigation).filter(Investigation.is_demo == 1).all():
        db.delete(inv)
        removed += 1
    db.commit()

    for doc in db.query(Document).filter(Document.is_demo == 1).all():
        document_service.delete_document(db, doc)
        removed += 1
    return removed
