"""Agent 1 - Evidence Collector.

Reads uploaded documents, extracts meaningful text sections and factual
statements, preserves provenance and stores observations and claims on the
blackboard. Does not invent missing content.
"""
from __future__ import annotations

from ..models import Claim, Document, DocumentContent, enums
from ..services import audit_service, document_service
from .base_agent import Action, AgentContext, AgentResult, BaseAgent


class EvidenceCollector(BaseAgent):
    name = "Evidence Collector"
    responsibility = "Extract observations and claims from documents while preserving provenance."
    required_inputs = ["processed documents (documents with extracted text and no claims yet)"]
    expected_outputs = ["observations", "claims (each carrying document provenance)"]
    run_conditions = [
        "at least one processed document has no extracted claims yet",
        "or AI assistance is enabled and a document with deterministic claims has no LLM attempt yet",
    ]
    stop_conditions = [
        "every processed document already has claims (and, if AI is enabled, an LLM attempt)",
        "no documents are in scope for the investigation",
    ]

    def _documents_awaiting_extraction(self, bb, ctx) -> list[Document]:
        docs = bb.documents(ctx.document_ids or None)
        pending = []
        for doc in docs:
            if doc.status != "processed":
                continue
            existing = [c for c in bb.claims([doc.id])]
            if not existing:
                pending.append(doc)
        return pending

    def _documents_awaiting_llm(self, bb, ctx) -> list[Document]:
        """Documents that already have deterministic claims but no LLM attempt yet."""
        if not ctx.enable_llm:
            return []
        docs = bb.documents(ctx.document_ids or None)
        pending = []
        for doc in docs:
            if doc.status != "processed":
                continue
            if not [c for c in bb.claims([doc.id])]:
                continue  # deterministic extraction must happen first
            if document_service.document_llm_attempted(bb.db, doc.id):
                continue
            pending.append(doc)
        return pending

    def candidates(self, bb: Blackboard, ctx: AgentContext) -> list[Action]:  # type: ignore[name-defined]
        pending = self._documents_awaiting_extraction(bb, ctx)
        llm_pending = self._documents_awaiting_llm(bb, ctx)
        work = pending + [d for d in llm_pending if d not in pending]
        if not work:
            return []
        llm_note = (
            " LLM assistance is enabled, so claims will also be augmented (and validated "
            "against the document text)."
            if ctx.enable_llm
            else ""
        )
        return [
            Action(
                agent_name=self.name,
                objective=f"Extract claims from {len(work)} document(s)",
                severity="medium",
                uncertainty=0.6,
                evidence_gap=0.9,
                info_gain=0.85,
                cost=0.05,
                reason="Documents have not yet had claims extracted; extraction is a prerequisite." + llm_note,
                payload={"document_ids": [d.id for d in work], "llm": ctx.enable_llm},
            )
        ]

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        doc_ids = action.payload.get("document_ids", [])
        use_llm = bool(action.payload.get("llm"))
        total_obs = 0
        total_claims = 0
        total_llm = 0
        events = []
        created_claim_ids: list[int] = []
        for doc_id in doc_ids:
            doc = bb.db.get(Document, doc_id)
            if doc is None or doc.status != "processed":
                continue
            content = (
                bb.db.query(DocumentContent)
                .filter(DocumentContent.document_id == doc_id)
                .first()
            )
            if content is None or not content.text.strip():
                doc.status = "error"
                doc.error_message = "No extractable text available for claim extraction."
                continue
            obs_added, claims_added = document_service.extract_document_content(bb.db, doc)
            llm_added = 0
            if use_llm:
                llm_added = document_service.augment_document_with_llm(
                    bb.db, doc, investigation_id=ctx.investigation_id, actor="llm"
                )
            total_obs += obs_added
            total_claims += claims_added
            total_llm += llm_added
            audit_service.record(
                bb.db,
                entity_type="claim",
                action="extracted",
                actor="llm" if (use_llm and llm_added) else "agent",
                investigation_id=ctx.investigation_id,
                summary=(
                    f"Extracted {claims_added} rule-based and {llm_added} LLM-suggested "
                    f"claim(s) and {obs_added} observation(s) from '{doc.filename}'."
                ),
                detail={
                    "document_id": doc_id,
                    "claims_added": claims_added,
                    "llm_claims_added": llm_added,
                    "observations_added": obs_added,
                },
            )
            for obj in bb.db.query(Claim).filter(Claim.document_id == doc_id).all():
                created_claim_ids.append(obj.id)
                events.append(
                    {
                        "event_type": enums.EventType.CLAIM_EXTRACTED.value,
                        "payload": {
                            "claim_id": obj.id,
                            "document_id": doc_id,
                            "claim_text": obj.claim_text[:200],
                            "claim_type": obj.claim_type,
                        },
                    }
                )
            events.append(
                {
                    "event_type": enums.EventType.DOCUMENT_PROCESSED.value,
                    "payload": {
                        "document_id": doc_id,
                        "filename": doc.filename,
                        "observations": obs_added,
                    },
                }
            )
        summary = f"Extracted {total_obs} observation(s) and {total_claims} claim(s)."
        if use_llm:
            summary += f" {total_llm} additional AI-suggested claim(s) were grounded and kept."
        return AgentResult(
            action="extract_claims",
            input_summary=f"Processed documents: {doc_ids}",
            output_summary=summary,
            changes={
                "observations_added": total_obs,
                "claims_added": total_claims,
                "llm_claims_added": total_llm,
            },
            events=events,
            input_record_ids=list(doc_ids),
            output_record_ids=sorted(set(created_claim_ids)),
        )
