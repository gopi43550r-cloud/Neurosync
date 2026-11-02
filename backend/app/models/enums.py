"""Enumerations shared across models, agents and schemas."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience
        return str(self.value)


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class ConflictType(StrEnum):
    DIRECT_CONTRADICTION = "direct_contradiction"
    NUMERICAL_DISAGREEMENT = "numerical_disagreement"
    TEMPORAL_INCONSISTENCY = "temporal_inconsistency"
    SOURCE_DISAGREEMENT = "source_disagreement"
    MISSING_CONTEXT = "missing_context"
    SEMANTIC_INCONSISTENCY = "semantic_inconsistency"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    INCONCLUSIVE = "inconclusive"
    HUMAN_REVIEW = "human_review"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    REVIEW_REQUIRED = "review_required"
    HUMAN_REVIEWED = "human_reviewed"


class EvidenceType(StrEnum):
    DOCUMENT_STATEMENT = "document_statement"
    CALIBRATION_RECORD = "calibration_record"
    TIMESTAMP = "timestamp"
    MEASUREMENT = "measurement"
    CONTEXTUAL = "contextual"
    USER_SUPPLIED = "user_supplied"
    MISSING = "missing"


class EvidenceOrigin(StrEnum):
    DOCUMENT = "document"
    USER = "user"
    INFERRED = "inferred"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNSUPPORTED = "unsupported"
    REQUIRES_REVIEW = "requires_review"


class FactVerdict(StrEnum):
    """Outcome of claim-level fact verification.

    Only four outcomes are permitted. ``UNVERIFIED`` is the safe default when
    the uploaded documents and recorded evidence do not decide the claim.
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNVERIFIED = "unverified"


class InvestigationStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class InvestigationStopReason(StrEnum):
    NO_CONFLICTS = "no_unresolved_conflicts"
    NO_USEFUL_ACTIONS = "no_useful_actions_remaining"
    ITERATION_LIMIT = "iteration_limit_reached"
    EXECUTION_LIMIT = "execution_limit_reached"
    CANCELLED = "cancelled_by_user"
    ERROR = "error_prevented_continuation"
    HUMAN_REVIEW = "human_review_required"
    COMPLETED = "investigation_converged"


class ConclusionType(StrEnum):
    SUPPORTED = "supported_conclusion"
    TENTATIVE = "tentative_conclusion"
    INCONCLUSIVE = "inconclusive"
    HUMAN_REVIEW = "human_review_required"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    REQUEST_MORE_INVESTIGATION = "request_more_investigation"
    REOPENED = "reopen"


class AgentStatus(StrEnum):
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_EVIDENCE = "waiting_for_evidence"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"


class ActivityStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class RecordType(StrEnum):
    """Kinds of blackboard records that can take part in a relation."""

    DOCUMENT = "document"
    OBSERVATION = "observation"
    CLAIM = "claim"
    CONFLICT = "conflict"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    CONCLUSION = "conclusion"
    INVESTIGATION = "investigation"
    AGENT_ACTION = "agent_action"
    VERIFICATION = "verification"


class RelationType(StrEnum):
    """Typed edges between blackboard records.

    Each value reads ``source <relation_type> target`` and mirrors the edges
    already exposed by ``blackboard/graph.py`` so the graph view and the
    relation table stay consistent.
    """

    EXTRACTED_FROM = "extracted_from"      # claim -> document
    DERIVED_FROM = "derived_from"          # conflict -> claim
    CONTRADICTS = "contradicts"            # conflict <-> claim
    HAS_EVIDENCE = "has_evidence"          # conflict -> evidence
    SUPPORTS = "supports"                  # evidence -> hypothesis
    REFUTES = "refutes"                    # evidence -> hypothesis
    EXPLAINS = "explains"                  # hypothesis -> conflict
    RESOLVED_BY = "resolved_by"            # conflict -> conclusion
    BASED_ON = "based_on"                  # hypothesis -> evidence
    INVESTIGATES = "investigates"          # investigation -> conflict
    PRODUCED = "produced"                  # agent -> record
    VERIFIED = "verified"                  # verification -> hypothesis


class ReevaluationKind(StrEnum):
    """How far an event-driven re-evaluation should re-open reasoning."""

    DETECT = "detect"
    HYPOTHESIZE = "hypothesize"
    INVESTIGATE = "investigate"
    VERIFY = "verify"
    DECIDE = "decide"


class EventType(StrEnum):
    INVESTIGATION_STARTED = "investigation_started"
    AGENT_SELECTED = "agent_selected"
    DOCUMENT_PROCESSED = "document_processed"
    CLAIM_EXTRACTED = "claim_extracted"
    CONFLICT_DETECTED = "conflict_detected"
    HYPOTHESIS_GENERATED = "hypothesis_generated"
    EVIDENCE_EVALUATED = "evidence_evaluated"
    HYPOTHESIS_VERIFIED = "hypothesis_verified"
    CONCLUSION_REACHED = "conclusion_reached"
    ITERATION_COMPLETED = "iteration_completed"
    INVESTIGATION_PAUSED = "investigation_paused"
    INVESTIGATION_RESUMED = "investigation_resumed"
    INVESTIGATION_COMPLETED = "investigation_completed"
    INVESTIGATION_CANCELLED = "investigation_cancelled"
    HUMAN_REVIEW_REQUESTED = "human_review_requested"
    HUMAN_REVIEW_RECORDED = "human_review_recorded"
    # Intelligence layer additions
    EVIDENCE_ADDED = "evidence_added"
    HYPOTHESIS_UPDATED = "hypothesis_updated"
    REEVALUATION_SCHEDULED = "reevaluation_scheduled"
