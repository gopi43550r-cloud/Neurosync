"""Agent 4 - Investigator.

Examines unresolved conflicts, retrieves relevant passages from the documents
actually available to the application, records investigation results as
evidence with provenance, and identifies information that is missing. It never
claims to access external databases, sensors or the internet.
"""
from __future__ import annotations

import json

from ..models import Claim, Conflict, Document, DocumentContent, Evidence, Hypothesis, enums
from ..services.evidence_service import create_evidence
from ..services import audit_service
from .base_agent import Action, AgentContext, AgentResult, BaseAgent

CONTEXT_KEYWORDS = ["calibrat", "timestamp", "recorded at", "at 0", "at 1", "at 2", "operating", "load"]


def _meta(conflict: Conflict) -> dict:
    try:
        return json.loads(conflict.meta or "{}")
    except json.JSONDecodeError:
        return {}


def _set_meta(conflict: Conflict, data: dict) -> None:
    conflict.meta = json.dumps(data)


class Investigator(BaseAgent):
    name = "Investigator"
    responsibility = "Gather relevant in-document evidence and identify missing information."
    required_inputs = [
        "an open/investigating conflict that already has hypotheses",
        "the document text available to the application",
    ]
    expected_outputs = [
        "evidence with provenance (calibration/timestamp/contextual)",
        "explicit 'missing' evidence recording information gaps",
    ]
    run_conditions = [
        "an in-scope conflict has hypotheses but has not been investigated yet",
    ]
    stop_conditions = [
        "every conflict with hypotheses has already been investigated",
        "no document text is available to search",
    ]

    def _targets(self, bb, ctx) -> list[Conflict]:
        conflicts = bb.conflicts(ids=ctx.conflict_ids or None)
        targets = []
        for c in conflicts:
            if c.status not in ("open", "investigating"):
                continue
            if not bb.hypotheses(c.id):
                continue
            if _meta(c).get("investigated"):
                continue
            targets.append(c)
        return targets

    def candidates(self, bb, ctx: AgentContext) -> list[Action]:
        actions = []
        for c in self._targets(bb, ctx):
            actions.append(
                Action(
                    agent_name=self.name,
                    objective=f"Search documents for evidence about conflict {c.id}",
                    conflict_id=c.id,
                    severity=c.severity,
                    uncertainty=0.65,
                    evidence_gap=0.8,
                    info_gain=0.8,
                    cost=0.12,
                    reason="Hypotheses exist but supporting in-document evidence has not been gathered.",
                    payload={"conflict_id": c.id},
                )
            )
        return actions

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        conflict = bb.db.get(Conflict, action.conflict_id)
        if conflict is None:
            return AgentResult(
                status="skipped",
                action="investigate",
                output_summary="Conflict not found.",
                input_record_ids=[action.conflict_id] if action.conflict_id else [],
            )

        hypotheses = bb.hypotheses(conflict.id)
        calibration_hyp = self._match(hypotheses, ["calibrat", "sensor", "drift", "measurement error"])
        change_hyp = self._match(hypotheses, ["genuine", "change", "different states", "different times"])
        condition_hyp = self._match(hypotheses, ["condition", "operating", "load"])
        reporting_hyp = self._match(hypotheses, ["incomplete", "reporting", "missing context"])

        document_ids = ctx.document_ids or [d.id for d in bb.documents()]
        added = 0
        added_ids: list[int] = []
        events = []
        found_calibration = False
        found_conditions = False

        for doc_id in document_ids:
            content = bb.db.query(DocumentContent).filter(DocumentContent.document_id == doc_id).first()
            if content is None or not content.text:
                continue
            doc = bb.db.get(Document, doc_id)
            text = content.text
            low = text.lower()

            if "calibrat" in low or "recalibrat" in low:
                found_calibration = True
                passage = self._passage(text, "calibrat")
                if not self._exists(bb, conflict.id, passage):
                    ev = create_evidence(
                        bb.db,
                        conflict_id=conflict.id,
                        description=f"Document '{doc.filename}' contains a calibration record: \"{passage}\"",
                        evidence_type="calibration_record",
                        origin="document",
                        document_id=doc_id,
                        source_reference=doc.filename,
                        source_location=doc.filename,
                        relevance_score=0.8,
                        reliability_score=0.8,
                        directness=0.85,
                        supports_hypothesis_id=calibration_hyp.id if calibration_hyp else None,
                        investigation_id=ctx.investigation_id,
                        actor="agent",
                    )
                    added_ids.append(ev.id)
                    added += 1

            if any(k in low for k in ["operating", "load", "conditions"]):
                found_conditions = True
                passage = self._passage(text, "operating")
                if not self._exists(bb, conflict.id, passage):
                    ev = create_evidence(
                        bb.db,
                        conflict_id=conflict.id,
                        description=f"Document '{doc.filename}' mentions operating conditions: \"{passage}\"",
                        evidence_type="contextual",
                        origin="document",
                        document_id=doc_id,
                        source_reference=doc.filename,
                        source_location=doc.filename,
                        relevance_score=0.5,
                        reliability_score=0.6,
                        directness=0.5,
                        supports_hypothesis_id=condition_hyp.id if condition_hyp else None,
                        investigation_id=ctx.investigation_id,
                        actor="agent",
                    )
                    added_ids.append(ev.id)
                    added += 1

        # Timestamp evidence: only meaningful when the conflicting readings were
        # actually taken at different times. Equal timestamps are not recorded as
        # a "difference", since none exists.
        claim_a = bb.db.get(Claim, conflict.claim_a_id)
        claim_b = bb.db.get(Claim, conflict.claim_b_id)
        if (
            claim_a
            and claim_b
            and claim_a.timestamp_value
            and claim_b.timestamp_value
            and claim_a.timestamp_value != claim_b.timestamp_value
        ):
            desc = (
                f"The conflicting readings carry different timestamps "
                f"({claim_a.timestamp_value.strftime('%H:%M')} vs {claim_b.timestamp_value.strftime('%H:%M')}), "
                "which is relevant to whether they are contemporaneous."
            )
            if not self._exists(bb, conflict.id, desc):
                ev = create_evidence(
                    bb.db,
                    conflict_id=conflict.id,
                    description=desc,
                    evidence_type="timestamp",
                    origin="document",
                    document_id=claim_a.document_id,
                    source_reference=claim_a.source_reference,
                    relevance_score=0.7,
                    reliability_score=0.7,
                    directness=0.8,
                    supports_hypothesis_id=change_hyp.id if change_hyp else None,
                    investigation_id=ctx.investigation_id,
                    actor="agent",
                )
                added_ids.append(ev.id)
                added += 1

        # Record unresolved gaps as explicit "missing" evidence (not invented facts).
        if not found_calibration and calibration_hyp:
            desc = "No calibration record was found in the available documents for this conflict."
            if not self._exists(bb, conflict.id, desc):
                ev = create_evidence(
                    bb.db,
                    conflict_id=conflict.id,
                    description=desc,
                    evidence_type="missing",
                    origin="inferred",
                    relevance_score=0.5,
                    reliability_score=0.2,
                    directness=0.2,
                    contradicts_hypothesis_id=calibration_hyp.id,
                    investigation_id=ctx.investigation_id,
                    actor="agent",
                )
                added_ids.append(ev.id)
                added += 1
        if not found_conditions and condition_hyp:
            desc = "No operating-condition data was found in the available documents for this conflict."
            if not self._exists(bb, conflict.id, desc):
                ev = create_evidence(
                    bb.db,
                    conflict_id=conflict.id,
                    description=desc,
                    evidence_type="missing",
                    origin="inferred",
                    relevance_score=0.5,
                    reliability_score=0.2,
                    directness=0.2,
                    contradicts_hypothesis_id=condition_hyp.id,
                    investigation_id=ctx.investigation_id,
                    actor="agent",
                )
                added_ids.append(ev.id)
                added += 1

        meta = _meta(conflict)
        meta["investigated"] = True
        _set_meta(conflict, meta)
        if conflict.status == "open":
            conflict.status = enums.ConflictStatus.INVESTIGATING.value

        llm_ids: list[int] = []
        if ctx.enable_llm:
            llm_ids = self._llm_evidence(bb, ctx, conflict, hypotheses, document_ids)
            added += len(llm_ids)

        events.append(
            {
                "event_type": enums.EventType.EVIDENCE_EVALUATED.value,
                "payload": {
                    "conflict_id": conflict.id,
                    "evidence_added": added,
                    "calibration_record_found": found_calibration,
                    "llm_evidence_added": len(llm_ids),
                },
            }
        )
        return AgentResult(
            action="investigate",
            conflict_id=conflict.id,
            input_summary=f"Searched {len(document_ids)} document(s) for conflict {conflict.id}.",
            output_summary=(
                f"Added {added} evidence item(s) from available documents"
                + (f" ({len(llm_ids)} AI-suggested, grounded in the text)." if llm_ids else ".")
            ),
            changes={"evidence_added": added, "llm_evidence_added": len(llm_ids)},
            events=events,
            input_record_ids=[conflict.id],
            output_record_ids=sorted(set(added_ids) | set(llm_ids)),
        )

    def _llm_evidence(self, bb, ctx, conflict, hypotheses, document_ids) -> list[int]:
        """Suggest contextual evidence, keeping only quotes present in the document.

        Every AI suggestion is labelled and stored with low directness and the
        ``inferred`` origin, so the Verification Agent treats it as requiring
        review rather than as established fact. Ungrounded quotes are discarded.
        """
        from ..services.llm_service import is_grounded, llm_service

        titles = [h.title for h in hypotheses]
        allowed_types = {"contextual", "measurement", "timestamp", "calibration_record", "document_statement"}
        added_ids: list[int] = []
        for doc_id in document_ids:
            content = bb.db.query(DocumentContent).filter(DocumentContent.document_id == doc_id).first()
            if content is None or not content.text:
                continue
            doc = bb.db.get(Document, doc_id)
            suggestions = llm_service.interpret_evidence(content.text, conflict.conflict_type, titles)
            for s in suggestions:
                quote = (s.quote or "").strip()
                if not quote or not is_grounded(quote, [content.text]):
                    continue
                if self._exists(bb, conflict.id, quote[:80]):
                    continue
                hyp = self._match_suggestion(hypotheses, s.supports_hypothesis)
                ev_type = s.evidence_type if s.evidence_type in allowed_types else "contextual"
                reason = (s.reason or "Relevant contextual statement.").strip()
                ev = create_evidence(
                    bb.db,
                    conflict_id=conflict.id,
                    description=f"[AI-suggested] {reason} Excerpt: \"{quote}\"",
                    evidence_type=ev_type,
                    origin="inferred",
                    document_id=doc_id,
                    source_reference=doc.filename if doc else "",
                    source_location=doc.filename if doc else "",
                    relevance_score=0.4,
                    reliability_score=0.3,
                    directness=0.25,
                    supports_hypothesis_id=hyp.id if hyp else None,
                    investigation_id=ctx.investigation_id,
                    actor="llm",
                )
                added_ids.append(ev.id)
        return added_ids

    @staticmethod
    def _match_suggestion(hypotheses: list[Hypothesis], name: str) -> Hypothesis | None:
        if not name:
            return None
        n = name.lower().strip()
        for h in hypotheses:
            t = h.title.lower()
            if n == t or n in t or t in n:
                return h
        return None

    @staticmethod
    def _match(hypotheses: list[Hypothesis], keywords: list[str]) -> Hypothesis | None:
        for h in hypotheses:
            low = h.title.lower()
            if any(k in low for k in keywords):
                return h
        return None

    @staticmethod
    def _passage(text: str, keyword: str, window: int = 180) -> str:
        low = text.lower()
        idx = low.find(keyword)
        if idx == -1:
            return text[:window].strip()
        start = max(0, idx - window // 2)
        end = min(len(text), idx + window)
        return text[start:end].strip().replace("\n", " ")

    @staticmethod
    def _exists(bb, conflict_id: int, marker: str) -> bool:
        marker = marker[:80]
        for ev in bb.db.query(Evidence).filter(Evidence.conflict_id == conflict_id).all():
            if marker and marker in ev.description:
                return True
        return False
