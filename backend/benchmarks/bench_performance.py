"""Reproducible performance/scale benchmark for NeuroSync.

This script is *measurement only*: it seeds a throwaway SQLite database with
synthetic data at a fixed scale, then times/records a fixed set of workloads that
correspond to the scalability questions in the brief (large event histories,
large document/claim lists, N+1 serialization, knowledge-graph scoping, relation
syncing, llm-attempt scans, snapshot graph building, blackboard assessment).

For every workload it records three machine-independent-or-comparable metrics:

* ``queries``  - number of SQL statements executed (catches N+1 / full-scans),
* ``ms``       - wall-clock time,
* ``peak_kb``  - peak Python heap allocated during the workload (tracemalloc).

Run it before and after an optimisation and diff the JSON reports::

    python benchmarks/bench_performance.py benchmarks/baseline.json
    python benchmarks/bench_performance.py benchmarks/improved.json

No numbers are hard-coded; everything printed is measured on the machine it runs
on. The synthetic data is deterministic (fixed RNG seed) so the two runs are
directly comparable.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Configure a throwaway database + uploads *before* importing the app, because
# engine/upload paths are resolved at import time.
_TMP = Path(tempfile.mkdtemp(prefix="neurosync_bench_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'bench.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["ENABLE_LLM"] = "false"
os.environ["OPENAI_API_KEY"] = ""

from sqlalchemy import event, insert  # noqa: E402

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app import models  # noqa: E402,F401  (register metadata)
from app.blackboard.blackboard_service import Blackboard  # noqa: E402
from app.blackboard import state as bb_state  # noqa: E402
from app.agents.base_agent import AgentContext  # noqa: E402
from app.services import document_service, knowledge_graph_service as kg, relation_service  # noqa: E402


# Fixed scale. Chosen to be large enough to expose O(n) work without making the
# benchmark take minutes.
SCALE = {
    "documents": 400,
    "claims_per_doc": 3,
    "observations_per_doc": 2,
    "conflicts": 600,
    "evidence": 1800,
    "hypotheses": 1200,
    "conclusions": 600,
    "human_reviews": 200,
    "events": 20000,
    "audit_events": 20000,
    "relations": 5000,
    "activities": 500,
    "scope_documents": 10,
    "scope_conflicts": 20,
    # Size of the synthetic upload used to measure streaming memory (bytes).
    "upload_bytes": 25 * 1024 * 1024,
}

_now = datetime(2026, 1, 1, 0, 0, 0)


class _PatternStream:
    """Readable stream that yields ``total`` bytes in bounded chunks.

    Used to benchmark upload streaming without allocating the whole payload up
    front: only one chunk exists in memory at a time.
    """

    def __init__(self, total: int, chunk: int = 1024 * 1024) -> None:
        self.remaining = total
        self.chunk = chunk

    def read(self, n: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        take = min(n if n and n > 0 else self.chunk, self.remaining)
        self.remaining -= take
        return b"x" * take


class _FakeUpload:
    """Minimal stand-in for ``starlette.UploadFile`` for ``save_upload``."""

    def __init__(self, filename: str, content_type: str, stream) -> None:
        self.filename = filename
        self.content_type = content_type
        self.file = stream


def _seed(db) -> int:
    """Insert deterministic synthetic data. Returns the scoped investigation id."""
    rng = random.Random(1234)

    # documents + contents
    docs = [
        {
            "filename": f"doc_{i}.txt",
            "stored_filename": f"stored_{i}.txt",
            "file_type": "txt",
            "content_type": "text/plain",
            "file_size": 1000 + i,
            "checksum": f"{i:064d}",
            "status": "processed",
            "is_demo": 0,
        }
        for i in range(1, SCALE["documents"] + 1)
    ]
    db.execute(insert(models.Document), docs)

    contents = [
        {
            "document_id": i,
            "text": f"Document {i} body. Machine {i} reached {70 + i % 30} C.",
            "page_map": "[]",
            "char_count": 60,
        }
        for i in range(1, SCALE["documents"] + 1)
    ]
    db.execute(insert(models.DocumentContent), contents)

    observations = []
    claims = []
    cid = 0
    for d in range(1, SCALE["documents"] + 1):
        for _ in range(SCALE["observations_per_doc"]):
            observations.append(
                {
                    "document_id": d,
                    "text": f"Observation for doc {d}",
                    "observation_type": "statement",
                    "source_location": f"doc_{d}.txt",
                    "extraction_method": "rule_based",
                    "metadata": "{}",
                }
            )
        for _ in range(SCALE["claims_per_doc"]):
            cid += 1
            claims.append(
                {
                    "document_id": d,
                    "claim_text": f"Claim {cid}: machine M-{d} measured value {rng.randint(60, 99)}C.",
                    "subject": f"machine M-{d}",
                    "predicate": "temperature",
                    "object_value": f"{rng.randint(60, 99)}C",
                    "numeric_value": float(rng.randint(60, 99)),
                    "unit": "C",
                    "polarity": "affirmative",
                    "claim_type": "measurement",
                    "source_reference": f"doc_{d}.txt",
                    "source_location": f"doc_{d}.txt",
                    "confidence": 0.6,
                    "metadata": "{}",
                }
            )
    db.execute(insert(models.Observation), observations)
    db.execute(insert(models.Claim), claims)
    db.commit()

    total_claims = len(claims)
    max_pair = total_claims // 2

    conflicts = []
    for i in range(1, SCALE["conflicts"] + 1):
        a = ((i - 1) % max_pair) * 2 + 1
        b = a + 1
        conflicts.append(
            {
                "claim_a_id": a,
                "claim_b_id": b,
                "conflict_type": "numerical_disagreement",
                "description": f"Conflict {i} between claim {a} and claim {b}.",
                "severity": rng.choice(["low", "medium", "high", "critical"]),
                "detection_method": "rule_based",
                "confidence": 0.5,
                "status": rng.choice(["open", "investigating", "resolved", "human_review"]),
                "metadata": "{}",
            }
        )
    db.execute(insert(models.Conflict), conflicts)
    db.commit()

    hypotheses = []
    for i in range(1, SCALE["hypotheses"] + 1):
        hypotheses.append(
            {
                "conflict_id": (i - 1) % SCALE["conflicts"] + 1,
                "title": f"Hypothesis {i}",
                "explanation": "Synthetic explanation.",
                "supporting_evidence_ids": "[]",
                "contradicting_evidence_ids": "[]",
                "assumptions": "[]",
                "missing_information": "[]",
                "confidence": 0.4,
                "support_score": 0.5,
                "status": rng.choice(["proposed", "supported", "inconclusive", "review_required"]),
                "origin": "agent",
            }
        )
    db.execute(insert(models.Hypothesis), hypotheses)

    evidence = []
    for i in range(1, SCALE["evidence"] + 1):
        conf = (i - 1) % SCALE["conflicts"] + 1
        evidence.append(
            {
                "conflict_id": conf,
                "claim_id": ((conf - 1) % max_pair) * 2 + 1,
                "document_id": (i - 1) % SCALE["documents"] + 1,
                "evidence_type": rng.choice(["measurement", "contextual", "missing"]),
                "origin": rng.choice(["document", "agent", "user"]),
                "description": f"Evidence {i} for conflict {conf}.",
                "source_reference": f"doc_{(i - 1) % SCALE['documents'] + 1}.txt",
                "source_location": "",
                "relevance_score": 0.5,
                "reliability_score": 0.5,
                "directness": 0.5,
                "verification_status": rng.choice(["unverified", "verified", "unsupported", "requires_review"]),
                "metadata": "{}",
            }
        )
    db.execute(insert(models.Evidence), evidence)

    conclusions = []
    for i in range(1, SCALE["conclusions"] + 1):
        conclusions.append(
            {
                "investigation_id": 1,  # fixed up after the investigation exists
                "conflict_id": (i - 1) % SCALE["conflicts"] + 1,
                "decision_type": rng.choice(["inconclusive", "human_review_required", "resolved_by_evidence"]),
                "conclusion": f"Conclusion {i}.",
                "confidence": 0.4,
                "supporting_evidence_ids": "[]",
                "unresolved_questions": "[]",
                "limitations": "[]",
            }
        )

    # The scoped investigation: created first so FK ids line up. Several
    # investigations exist so every event/audit/activity row has a valid parent.
    investigations = [
        {
            "id": i,
            "name": f"Benchmark investigation {i}",
            "research_question": "Why do readings disagree?",
            "status": "completed",
            "iteration_limit": 25,
            "min_evidence_threshold": 1,
            "enable_llm": 0,
            "iteration_count": 7,
            "stop_reason": "no_useful_actions_remaining",
            "is_demo": 1 if i == 1 else 0,
        }
        for i in range(1, 51)
    ]
    db.execute(insert(models.Investigation), investigations)
    db.commit()
    inv_id = 1

    db.execute(insert(models.Conclusion), conclusions)

    reviews = [
        {
            "conclusion_id": (i - 1) % SCALE["conclusions"] + 1,
            "conflict_id": (i - 1) % SCALE["conflicts"] + 1,
            "investigation_id": inv_id,
            "decision": rng.choice(["approved", "rejected", "request_more_investigation"]),
            "reviewer": "human reviewer",
            "note": "",
            "previous_decision_type": "inconclusive",
        }
        for i in range(1, SCALE["human_reviews"] + 1)
    ]
    db.execute(insert(models.HumanReview), reviews)

    events = [
        {
            "investigation_id": (i % 50) + 1,
            "event_type": "evidence_added",
            "agent_name": "Investigator",
            "entity_type": "evidence",
            "entity_id": i,
            "payload": "{}",
            "created_at": _now,
        }
        for i in range(1, SCALE["events"] + 1)
    ]
    db.execute(insert(models.EventLog), events)

    audit = [
        {
            "investigation_id": (i % 50) + 1,
            "conflict_id": (i % SCALE["conflicts"]) + 1,
            "entity_type": "document" if i % 3 == 0 else "evidence",
            "entity_id": (i % SCALE["documents"]) + 1,
            "action": "llm_augmented" if i % 3 == 0 else "created",
            "actor": "agent",
            "summary": f"Audit {i}",
            "detail": json.dumps({"document_id": (i % SCALE["documents"]) + 1}),
            "created_at": _now,
        }
        for i in range(1, SCALE["audit_events"] + 1)
    ]
    db.execute(insert(models.AuditEvent), audit)

    relations = []
    for i in range(1, SCALE["relations"] + 1):
        relations.append(
            {
                "investigation_id": (i % 50) + 1,
                "source_type": "conflict",
                "source_id": i,
                "target_type": "evidence",
                "target_id": i,
                "relation_type": "has_evidence",
                "agent_name": "Investigator",
                "reason": "",
            }
        )
    db.execute(insert(models.BlackboardRelation), relations)

    activities = [
        {
            "investigation_id": inv_id if i % 2 else (i % 50) + 1,
            "conflict_id": (i % SCALE["conflicts"]) + 1,
            "agent_name": rng.choice(
                ["Evidence Collector", "Conflict Detector", "Hypothesis Generator",
                 "Investigator", "Verification Agent", "Decision Agent"]
            ),
            "action": "act",
            "input_summary": "",
            "output_summary": "",
            "reason": "",
            "blackboard_changes": "{}",
            "status": "success",
            "duration_ms": 5,
            "sequence": i,
            "attempt": 1,
            "input_record_ids": "[]",
            "output_record_ids": json.dumps([]),
            "error": "",
            "state_summary": "",
        }
        for i in range(1, SCALE["activities"] + 1)
    ]
    db.execute(insert(models.AgentActivity), activities)

    # Link the scoped investigation to a *small* slice of the data.
    db.execute(
        insert(models.investigation_documents),
        [{"investigation_id": inv_id, "document_id": d} for d in range(1, SCALE["scope_documents"] + 1)],
    )
    db.execute(
        insert(models.investigation_conflicts),
        [{"investigation_id": inv_id, "conflict_id": c} for c in range(1, SCALE["scope_conflicts"] + 1)],
    )
    db.commit()
    return int(inv_id)


# ----------------------------------------------------------------- measurement
def measure(fn) -> dict:
    counter = {"n": 0}

    def _before(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - start) * 1000.0
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    event.remove(engine, "before_cursor_execute", _before)
    return {"queries": counter["n"], "ms": round(ms, 2), "peak_kb": round(peak / 1024.0, 1), "result": result}


def _main(out_path: str | None) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()

    db = SessionLocal()
    inv_id = _seed(db)
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app

    context = AgentContext(
        investigation_id=inv_id,
        investigation_name="bench",
        research_question="?",
        document_ids=list(range(1, SCALE["scope_documents"] + 1)),
        conflict_ids=list(range(1, SCALE["scope_conflicts"] + 1)),
        enable_llm=False,
        min_evidence=1,
    )

    report: dict[str, dict] = {}

    with TestClient(app) as client:
        def ep(path: str, **params):
            def _run():
                resp = client.get(path, params=params)
                return {"status": resp.status_code, "total": resp.json().get("total")}
            return _run

        report["GET /api/blackboard/events"] = measure(ep("/api/blackboard/events", page_size=50))
        report["GET /api/audit"] = measure(ep("/api/audit", page_size=50))
        report["GET /api/claims"] = measure(ep("/api/claims", page_size=50))
        report["GET /api/documents"] = measure(ep("/api/documents", page_size=50))
        report["GET /api/conflicts"] = measure(ep("/api/conflicts", page_size=50))
        report["GET /api/evidence"] = measure(ep("/api/evidence", page_size=50))
        report["GET /api/hypotheses"] = measure(ep("/api/hypotheses", page_size=50))
        report["GET /api/investigations"] = measure(ep("/api/investigations", page_size=50))

    def _kg_scoped():
        g = kg.build_knowledge_graph(db, investigation_id=inv_id)
        return {"nodes": len(g["nodes"]), "edges": len(g["edges"])}

    def _kg_global():
        g = kg.build_knowledge_graph(db)
        return {"nodes": len(g["nodes"]), "edges": len(g["edges"])}

    def _sync_relations():
        return {"created": relation_service.sync_relations(db, investigation_id=inv_id)}

    def _llm_attempted():
        return {"attempted": document_service.document_llm_attempted(db, 1)}

    def _snapshot_graph():
        from app.blackboard.graph import build_graph
        g = build_graph(db)
        return {"nodes": len(g["nodes"]), "edges": len(g["edges"])}

    def _assess():
        return bb_state.assess(Blackboard(db), context).as_dict()

    report["kg.build_knowledge_graph(scoped)"] = measure(_kg_scoped)
    report["kg.build_knowledge_graph(global)"] = measure(_kg_global)
    report["relation_service.sync_relations(scoped)"] = measure(_sync_relations)
    report["document_service.document_llm_attempted"] = measure(_llm_attempted)
    report["blackboard.build_graph(global)"] = measure(_snapshot_graph)
    report["blackboard.state.assess(scoped)"] = measure(_assess)

    # document_stats is the N+1 that document listing hits per row.
    def _doc_stats_one():
        return document_service.document_stats(db, 1)

    report["document_service.document_stats(single)"] = measure(_doc_stats_one)

    # Large upload: peak memory should track the read chunk, not the file size.
    def _save_upload():
        upload = _FakeUpload("bench_upload.txt", "text/plain", _PatternStream(SCALE["upload_bytes"]))
        doc = document_service.save_upload(upload)
        document_service.discard_uncommitted(doc)
        return {"bytes": doc.file_size}

    report["document_service.save_upload(memory)"] = measure(_save_upload)

    db.close()

    payload = {"scale": SCALE, "workloads": report}
    text = json.dumps(payload, indent=2)
    print(text)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"\nwrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", default=None, help="optional JSON output path")
    args = parser.parse_args()
    _main(args.out)
