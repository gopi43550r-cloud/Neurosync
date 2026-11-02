"""Consistency service: keep the blackboard internally coherent.

Two responsibilities:

* **Duplicate prevention** - :func:`find_duplicate_evidence` /
  :func:`is_duplicate_evidence` detect when the *same* evidence (same conflict,
  same normalised description, same type) is about to be added twice. The
  evidence service consults this before inserting, so duplicates never enter the
  blackboard rather than being cleaned up afterwards.
* **Validation** - :func:`validate_blackboard` performs a read-only audit of the
  blackboard scope and returns every structural problem it can prove (evidence
  attributed to a hypothesis in another conflict, hypotheses without a conflict,
  conclusions pointing at missing conflicts, relations pointing at missing
  records, exact-duplicate evidence). It never mutates anything, so it is safe
  to call at any time.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BlackboardRelation,
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    Hypothesis,
    Investigation,
)

_WS = re.compile(r"\s+")


def normalize_description(text: str) -> str:
    """Casefold and collapse whitespace so trivially-different text matches."""
    return _WS.sub(" ", (text or "").strip().lower())


def _evidence_scope(db: Session, conflict_id: int | None):
    stmt = select(Evidence)
    if conflict_id is not None:
        stmt = stmt.where(Evidence.conflict_id == conflict_id)
    return list(db.execute(stmt).scalars())


def find_duplicate_evidence(
    db: Session,
    *,
    conflict_id: int,
    description: str,
    evidence_type: str,
    exclude_id: int | None = None,
) -> Evidence | None:
    """Return an existing evidence row identical to the candidate, if any."""
    target = normalize_description(description)
    if not target:
        return None
    for ev in _evidence_scope(db, conflict_id):
        if exclude_id is not None and ev.id == exclude_id:
            continue
        if ev.evidence_type != evidence_type:
            continue
        if normalize_description(ev.description) == target:
            return ev
    return None


def is_duplicate_evidence(
    db: Session,
    *,
    conflict_id: int,
    description: str,
    evidence_type: str,
    exclude_id: int | None = None,
) -> bool:
    return (
        find_duplicate_evidence(
            db,
            conflict_id=conflict_id,
            description=description,
            evidence_type=evidence_type,
            exclude_id=exclude_id,
        )
        is not None
    )


def _record_exists(db: Session, record_type: str, record_id: int) -> bool:
    model = {
        "document": Document,
        "claim": Claim,
        "conflict": Conflict,
        "evidence": Evidence,
        "hypothesis": Hypothesis,
        "conclusion": Conclusion,
        "investigation": Investigation,
    }.get(record_type)
    if model is None:
        return True  # unknown types (e.g. agent_action) are not checked
    return db.get(model, record_id) is not None


def validate_blackboard(db: Session, investigation_id: int | None = None) -> dict[str, Any]:
    """Read-only structural audit. Returns ``{"ok": bool, "issues": [...]}``."""
    issues: list[dict[str, Any]] = []

    if investigation_id is not None:
        inv = db.get(Investigation, investigation_id)
        if inv is None:
            return {"ok": False, "issues": [{"kind": "investigation_missing", "investigation_id": investigation_id}]}
        conflicts = list(inv.conflicts)
        conflict_ids = {c.id for c in conflicts}
    else:
        conflicts = list(db.execute(select(Conflict)).scalars())
        conflict_ids = {c.id for c in conflicts}

    hypotheses = list(db.execute(select(Hypothesis)).scalars())
    hyp_by_id = {h.id: h for h in hypotheses}

    # Duplicate evidence (same conflict + type + normalised description).
    seen: dict[tuple[int, str, str], int] = {}
    for ev in db.execute(select(Evidence)).scalars():
        if investigation_id is not None and ev.conflict_id not in conflict_ids:
            continue
        key = (ev.conflict_id, ev.evidence_type, normalize_description(ev.description))
        if key in seen:
            issues.append(
                {
                    "kind": "duplicate_evidence",
                    "conflict_id": ev.conflict_id,
                    "evidence_id": ev.id,
                    "duplicate_of": seen[key],
                }
            )
        else:
            seen[key] = ev.id

    # Evidence attributed to a hypothesis that does not exist or belongs to
    # another conflict.
    for ev in db.execute(select(Evidence)).scalars():
        if investigation_id is not None and ev.conflict_id not in conflict_ids:
            continue
        for attr in ("supports_hypothesis_id", "contradicts_hypothesis_id"):
            hyp_id = getattr(ev, attr)
            if not hyp_id:
                continue
            hyp = hyp_by_id.get(hyp_id)
            if hyp is None:
                issues.append(
                    {"kind": "evidence_missing_hypothesis", "evidence_id": ev.id, "hypothesis_id": hyp_id}
                )
            elif hyp.conflict_id != ev.conflict_id:
                issues.append(
                    {
                        "kind": "evidence_conflict_mismatch",
                        "evidence_id": ev.id,
                        "hypothesis_id": hyp_id,
                        "evidence_conflict_id": ev.conflict_id,
                        "hypothesis_conflict_id": hyp.conflict_id,
                    }
                )

    # Hypotheses whose conflict does not exist.
    for hyp in hypotheses:
        if investigation_id is not None and hyp.conflict_id not in conflict_ids:
            continue
        if db.get(Conflict, hyp.conflict_id) is None:
            issues.append({"kind": "hypothesis_missing_conflict", "hypothesis_id": hyp.id, "conflict_id": hyp.conflict_id})

    # Conclusions pointing at a missing conflict.
    conclusions = list(db.execute(select(Conclusion)).scalars())
    for cc in conclusions:
        if cc.conflict_id and db.get(Conflict, cc.conflict_id) is None:
            issues.append({"kind": "conclusion_missing_conflict", "conclusion_id": cc.id, "conflict_id": cc.conflict_id})

    # Relations pointing at missing records.
    for rel in db.execute(select(BlackboardRelation)).scalars():
        if investigation_id is not None and rel.investigation_id not in (None, investigation_id):
            continue
        if not _record_exists(db, rel.source_type, rel.source_id):
            issues.append({"kind": "relation_dangling_source", "relation_id": rel.id, "source_type": rel.source_type, "source_id": rel.source_id})
        if not _record_exists(db, rel.target_type, rel.target_id):
            issues.append({"kind": "relation_dangling_target", "relation_id": rel.id, "target_type": rel.target_type, "target_id": rel.target_id})

    return {"ok": not issues, "issues": issues}
