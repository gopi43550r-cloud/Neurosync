"""Agent registry."""
from .base_agent import Action, AgentContext, AgentResult, BaseAgent
from .conflict_detector import ConflictDetector
from .decision_agent import DecisionAgent
from .evidence_collector import EvidenceCollector
from .hypothesis_generator import HypothesisGenerator
from .investigator import Investigator
from .verification_agent import VerificationAgent


def default_agents() -> list[BaseAgent]:
    return [
        EvidenceCollector(),
        ConflictDetector(),
        HypothesisGenerator(),
        Investigator(),
        VerificationAgent(),
        DecisionAgent(),
    ]


AGENT_RESPONSIBILITIES = {
    "Evidence Collector": "Extract observations and claims from documents while preserving provenance.",
    "Conflict Detector": "Identify potential contradictions between claims and record them.",
    "Hypothesis Generator": "Propose competing, evidence-linked explanations for each conflict.",
    "Investigator": "Gather relevant in-document evidence and identify missing information.",
    "Verification Agent": "Evaluate hypotheses against evidence and compute transparent support scores.",
    "Decision Agent": "Decide whether a defensible conclusion can be drawn and produce it.",
}


def agent_manifests() -> list[dict]:
    """Declarative contracts (responsibility, inputs, outputs, conditions) for
    every registered agent."""
    return [agent.manifest() for agent in default_agents()]


__all__ = [
    "Action",
    "AgentContext",
    "AgentResult",
    "BaseAgent",
    "ConflictDetector",
    "DecisionAgent",
    "EvidenceCollector",
    "HypothesisGenerator",
    "Investigator",
    "VerificationAgent",
    "default_agents",
    "agent_manifests",
    "AGENT_RESPONSIBILITIES",
]
