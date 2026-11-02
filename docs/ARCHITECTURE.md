# NeuroSync — Architecture

This document explains how NeuroSync is structured and why. It describes the
blackboard model, the agents, the scheduler, the conflict-detection rules, the
evidence scoring model and the real-time pipeline.

---

## 1. Design principles

1. **The blackboard is the only shared state.** Agents never call each other.
   Each agent *reads* the blackboard, decides whether it has useful work, and
   *writes* new entities (claims, conflicts, evidence, hypotheses, conclusions).
2. **Opportunistic control.** There is no fixed workflow. A scheduler evaluates
   every agent each cycle and runs whichever action is currently most valuable.
3. **Deterministic by default.** Without an API key the entire pipeline uses
   transparent, rule-based logic, so any result can be reproduced and audited.
4. **No forced conclusions.** If the evidence is insufficient, the Decision Agent
   says so rather than inventing an answer.
5. **Every decision is explained.** Activities, reasons, scheduler breakdowns and
   conflict rationales are persisted and surfaced in the UI.

---

## 2. The blackboard model

The blackboard is stored in a relational database (SQLite by default). The
persistent entities form a chain of provenance:

```
Document ──▶ Observation ──▶ Claim ──┐
                                     ├──▶ Conflict ──▶ Evidence ──▶ Hypothesis ──▶ Conclusion
Document ──▶ Observation ──▶ Claim ──┘
```

| Entity          | Meaning                                                                |
| --------------- | ---------------------------------------------------------------------- |
| `Document`      | An uploaded or seeded source, plus its extracted text (`DocumentContent`). |
| `Observation`   | A raw sentence-level observation extracted from a document.            |
| `Claim`         | A structured assertion (subject, predicate, value, unit, polarity, time). |
| `Conflict`      | A detected contradiction between two claims, with type and severity.   |
| `Evidence`      | Anything that bears on a conflict, with origin/reliability/directness. |
| `Hypothesis`    | A candidate explanation for a conflict, later scored.                  |
| `Conclusion`    | The Decision Agent's final assessment for a conflict.                   |
| `AgentActivity` | An audit log of every agent action, its reason and its blackboard delta.|
| `EventLog`      | An append-only stream of events used by the SSE endpoint.              |

`Blackboard` (`blackboard/blackboard_service.py`) is a thin, read/write facade
over these models. The `blackboard/graph.py` module projects the entities into a
node/edge graph for the UI.

---

## 3. Data flow

1. **Ingest** — files are uploaded (`POST /api/documents/upload`), text is
   extracted (PyMuPDF for PDF, python-docx for DOCX, direct read for text
   formats), and — for uploads — claims/observations are extracted immediately.
2. **Detect** — the Conflict Detector compares claims sharing a subject across
   documents and records any contradictions.
3. **Hypothesize** — the Hypothesis Generator proposes competing explanations for
   each open conflict.
4. **Investigate** — the Investigator pulls additionally relevant evidence from
   the documents (calibration records, timestamps, corroborating statements).
5. **Verify** — the Verification Agent scores each hypothesis from the evidence.
6. **Decide** — the Decision Agent synthesises a conclusion and sets the final
   conflict status.
7. **Report** — conclusions are summarised into an exportable report.

Steps 2–6 are driven by the scheduler, not by a hard-coded order.

---

## 4. Agents

All agents derive from `BaseAgent` and implement `candidates()` (what work is
available) and `run()` (do the work). Each agent also declares a contract
(`required_inputs`, `expected_outputs`, `run_conditions`, `stop_conditions`)
exposed via `manifest()` and `GET /agents`. `safe_run()` wraps `run()` with
failure isolation: a failing attempt is rolled back (no partial writes, no
crash) and returned as a structured `failed` result that the controller can
retry. See `docs/orchestration.md` for the full orchestration design.

| Agent                    | Reads                                              | Writes                          |
| ------------------------ | -------------------------------------------------- | ------------------------------- |
| **Evidence Collector**   | Documents in scope                                 | Observations, Claims            |
| **Conflict Detector**    | Claims                                             | Conflicts                       |
| **Hypothesis Generator** | Conflicts                                          | Hypotheses                      |
| **Investigator**         | Conflicts, documents, existing evidence            | Evidence                        |
| **Verification Agent**   | Evidence, hypotheses                               | Updated hypothesis scores/status|
| **Decision Agent**       | Scored hypotheses, evidence                        | Conclusions, conflict status    |

Each candidate action carries scheduling inputs: `severity`, `uncertainty`,
`evidence_gap`, `info_gain` and `cost`.

---

## 5. The scheduler

`blackboard/scheduler.py` collects every candidate action from every available
agent, scores them, and returns the highest-priority one.

**Priority formula** (`scoring_service.scheduler_priority`, normalized to 0–100):

```
Priority = 100 × ( w_sev · Severity
                 + w_unc · Uncertainty
                 + w_gap · EvidenceGap
                 + w_gain · InfoGain ) − Cost × 15
```

Default weights (normalized to sum to 1): severity `0.30`, uncertainty `0.25`,
evidence gap `0.25`, information gain `0.20`.

**Severity mapping** (`SEVERITY_WEIGHT`): low `0.25`, medium `0.50`, high `0.75`,
critical `1.0`.

The scheduler's decision, its factor breakdown, its numeric priority and the
`BlackboardState` it was derived from are recorded on the resulting
`AgentActivity` and streamed as an event, so the choice is always explainable.

### Execution ledger

Every execution records a `sequence` (its position in the run), an `attempt`
(1 = first try, >1 = retry), the `input_record_ids` / `output_record_ids` it
touched, any `error`, and the `state_summary` the decision was based on. Each
retry is its own row, so the run is fully auditable.

### Stop conditions (controller)

An investigation stops when any of the following holds:

- **No candidates** remain (all agents have no available work).
- The best **priority < `MIN_PRIORITY` (5.0)**.
- The **iteration limit** is reached.
- The **execution limit** (`MAX_AGENT_EXECUTIONS`) is reached, counting retries —
  reported as `execution_limit_reached`.
- **Cancelled** by the user.
- An **error** prevents continuation.
- Every remaining agent has been **exhausted** (returned `skipped`/`failed`) in a
  single pass without any successful action — reported as
  `no_useful_actions_remaining`.

Congestion is avoided three ways: an agent that returns `skipped`/`failed` is
added to an `exhausted` set so it is not re-selected; that set is cleared whenever
any agent successfully changes the blackboard (which may reopen work); and an
action that repeats `MAX_ATTEMPTS_PER_ACTION` times without a change is parked.
Failed actions are retried up to `AGENT_MAX_RETRIES` times before the agent is
parked, so a single failure never aborts the investigation.

---

## 6. Conflict detection rules

`services/conflict_service.py` is deterministic and conservative. It only
compares claims that **share a property** (the predicate, falling back to the
subject) and come from **different documents**, and it never classifies every
numerical difference as a contradiction. A guard rejects any pair whose property
differs, preventing false conflicts between unrelated quantities on the same
subject. Each conflict's `meta` records the matched subject, property and reason.

| Type                    | Trigger                                                                 | Severity |
| ----------------------- | ----------------------------------------------------------------------- | -------- |
| `direct_contradiction`  | Same predicate, opposite polarity (e.g. "vibration" present vs absent)  | high     |
| `numerical_disagreement`| Same unit, values differ > 2% with no distinguishing context; > 25% → high | medium/high |
| `temporal_inconsistency`| Values differ but timestamps are > 30 minutes apart (may be real change) | medium   |
| `missing_context`       | Units differ/missing, or only one side has a timestamp                  | low/medium |
| `semantic_inconsistency`| Truthy states differ in wording                                         | medium   |

Tolerance: a relative difference ≤ **2%** is treated as agreement. Duplicate
conflicts (same claim pair + type) are never created.

---

## 7. Evidence and hypothesis scoring

`services/scoring_service.py` implements transparent heuristics. Scores are
**bounded support indicators, not calibrated probabilities**.

**Single evidence weight:**

```
weight = 0.40 · relevance + 0.35 · reliability + 0.25 · directness
```

Baseline reliability by origin: document `0.60`, user `0.55`, inferred `0.35`.
Reliability by type (examples): calibration record `0.85`, timestamp `0.75`,
measurement `0.70`, document statement `0.60`, missing `0.20`.

### Multi-factor evidence assessment

Independently of the hypothesis scoring above, every evidence item returned by
the API also carries an inspectable `assessment` object built by
`services/assessment_service.py`. It reports each factor with a `value`, a human
`label` and an `explanation`, so a user can see *why* an item is strong or weak:

```
overall = 0.35·relevance + 0.25·provenance + 0.15·recency
        + 0.15·completeness + 0.10·corroboration
overall ×= 0.85   when contradictory evidence exists
```

- **relevance** — overlap between the evidence text and the claim it concerns.
- **provenance** — origin/type reliability (document > user > inferred).
- **recency** — freshness of the *source* timestamp (claim time or source-document
  processing time); labelled `unknown` when no source timestamp exists (the
  evidence record's own creation time is deliberately not used, since it says
  nothing about how fresh the source is).
- **completeness** — how many expected fields (description, type, unit,
  timestamp, source reference) are present.
- **corroboration** — how many distinct sources agree.

The object also reports a `source_reliability` label (explicitly `"unknown"` when
the source cannot be judged, rather than inventing a value), a
`missing_information` list, the `formula`, and a `caveat` stating the score is a
bounded support indicator, not a calibrated probability. It is attached to
`EvidenceOut` and rendered in the Evidence page.

**Hypothesis support:** positive weights are summed (with repeated evidence from
the same document down-weighted by `1 / (1 + 0.5·dup_index)` to prevent counting
one source as independent corroboration), negative weights are subtracted with a
`0.75` factor, and the result is soft-saturated into `[0, 1]`.

Status thresholds: `contradicted` when contradictions dominate; `supported` when
support ≥ `0.62` with direct evidence (or ≥ `0.55` generally); otherwise
`inconclusive`. A `supported` hypothesis backed by a single source is downgraded
to `review_required`.

---

## 8. Decision logic

The Decision Agent only runs for a conflict once every hypothesis has a
non-`proposed` status and no conclusion exists yet. It compares the top two
hypotheses by support and applies conservative thresholds:

| Condition                                                                 | Decision              |
| ------------------------------------------------------------------------- | --------------------- |
| top `supported`, support ≥ 0.70, margin ≥ 0.15, ≥ 2 distinct sources      | `supported_conclusion`|
| conflict in `human_review` and margin < 0.12                              | `human_review_required`|
| support ≥ 0.55, margin ≥ 0.1, status `supported`/`review_required`        | `tentative_conclusion`|
| otherwise                                                                 | `inconclusive`        |

The conclusion updates the conflict's status to `resolved`, `human_review` or
`inconclusive` accordingly.

---

## 9. Real-time events

Every meaningful change is appended to the `EventLog` and published to an
in-process event bus (`blackboard/events.py`). `GET
/api/investigations/{id}/events` streams them as **Server-Sent Events** with
`id`, `event` (the event type) and a JSON `data` envelope. Event types include
`investigation_started`, `agent_selected`, `claim_extracted`,
`conflict_detected`, `hypothesis_generated`, `evidence_evaluated`,
`hypothesis_verified`, `conclusion_reached`, `iteration_completed`,
`investigation_completed`, `human_review_requested` and
`human_review_recorded`.

The stream is built for reliability:

* **Replayable.** The SSE `id` is the event's database id. If the connection
  drops, the browser's `EventSource` reconnects and the server resumes from the
  `Last-Event-ID` header, so no event is lost or re-sent.
* **Authoritative progress.** A `progress` frame derived from persisted rows
  (status, current agent, iteration counts, completed/failed/skipped execution
  tallies) is emitted on connect and whenever the state changes. Progress is
  real backend state, never a simulated percentage.
* **Redacted.** `services/event_redaction.py` strips raw claim/document text from
  every payload at the serialization boundary (SSE and the blackboard events
  list), so sensitive document content never reaches a client. The persisted log
  keeps the full payload for audit and traceability.
* **Terminates deterministically.** An unknown investigation emits
  `stream_error`; a terminal investigation drains, emits `stream_end` and
  closes.

The frontend subscribes with `EventSource`, seeds a rolling, de-duplicated
buffer from the persisted event log (so the panel is populated even before the
stream connects and after reloads), and refreshes authoritative data whenever an
event or progress frame arrives. Reconnection state (`connecting`,
`reconnecting`, `open`, `ended`, `error`) is shown in the UI with a manual
reconnect affordance on failure. In-flight investigations can be stopped safely
at any point via the controller's cooperative cancellation.

---

## 10. Concurrency and lifecycle

Investigations run in a background thread (`investigation_service._run_thread`).
An `InvestigationRegistry` tracks running investigations, prevents duplicate
simultaneous investigations over the same documents/conflicts, and exposes
pause/resume/cancel controls. A fresh database session is created per run.

---

## 11. Optional LLM assistance

The LLM layer is a *complement*, never a dependency: conflict detection, scoring,
verification and decision logic always remain deterministic, and the application
runs fully without any API key.

### Provider interface

`services/llm_service.py` defines an `LLMProvider` ABC and an
`OpenAICompatibleProvider` (works with OpenAI and any OpenAI-compatible base URL,
e.g. a local model server or proxy). `LLMService` wraps a provider and exposes
validated, task-level methods — `extract_claims`, `generate_hypotheses`,
`interpret_evidence`, `explain_hypothesis`, `explain_decision` and
`assess_conflict` — plus a low-level `structured()` JSON call. Failures
(timeout, `429`, `5xx`, network errors, malformed JSON) are retried with backoff
and then reported as no-output, so callers degrade to deterministic behaviour.
The API key is sent only in the `Authorization` header and is never logged or
returned.

### Activation and mode selection

Two layers control whether AI is used:

1. **Deployment** — `ENABLE_LLM=true` **and** a configured key make the provider
   *available* (`llm_configured`).
2. **User preference** — a global `reasoning_mode` (`deterministic` /
   `ai_assisted`) stored in the `app_settings` table and toggled from Settings.
   `services/settings_service.py` computes the `effective_mode`, degrading to
   `deterministic` (with a human-readable note) when the provider is not
   available.

Per-investigation `enable_llm` is ANDed with the global mode as an opt-out. Each
agent hook checks the resolved flag on the controller's execution context.

### Grounding and prompt-injection hardening

Document text is untrusted input, so the system treats model output as untrusted
too:

- **Data delimiters.** Document text is wrapped between `DATA_OPEN`/`DATA_CLOSE`
  markers (which are stripped from the data itself) and the system prompt forbids
  following instructions embedded in documents.
- **Verbatim grounding.** `is_grounded()` requires any supporting quote the model
  returns to appear in the source text (whitespace/case-insensitive) at a minimum
  length, or it is dropped.
- **Citation validation.** `valid_evidence_ids()` checks that every cited id is a
  real evidence record for the conflict; an explanation citing fabricated
  evidence is rejected entirely.
- **Provenance.** LLM-derived claims, hypotheses and evidence are tagged
  (`ai_suggested`, `origin="llm"`/`inferred`) so they are always distinguishable
  from rule-based output.

The Conflict Detector uses the model only as a *second opinion* and never lets it
create conflicts on its own; the Verification Agent validates LLM explanations
before recording them.

---

## 12. Explainability, audit trail and human review

Three services make the reasoning inspectable and accountable:

- **`services/ranking_service.py`** — ranks the hypotheses for a conflict by
  documented evidence weight (`support_score`, then `confidence` as a
  deterministic tie-break). For every hypothesis it returns the supporting and
  contradicting evidence, the criteria that produced the score (supporting and
  contradicting weight, distinct sources, whether direct evidence exists), the
  assumptions and missing information, and the margin to the next explanation.
  Every score is labelled a *bounded support indicator*, never a calibrated
  probability.

- **`services/audit_service.py`** — an append-only `audit_events` table records
  every blackboard change (`entity_type`, `entity_id`, `action`, `actor`,
  `summary`, structured `detail`, timestamp). Agents write as `actor="agent"`;
  humans write under their own name. Entries are flushed on the current session
  so they commit atomically with the change they describe, and cascade with the
  investigation.

- **`services/review_service.py`** — records a human decision on a conclusion.
  Five decisions are supported, each mapped to a conflict status:
  `approved` → `resolved`, `rejected` → `open`,
  `request_more_investigation` → `human_review`, `inconclusive` → `inconclusive`,
  and `reopen` → `open` (to re-open a previously reviewed conflict for another
  pass). The `human_reviews` row stores the decision, reviewer, note, the
  conclusion's previous decision type and a timestamp; the decision is written to
  the audit trail and published as a `human_review_recorded` event.

The investigation report surfaces all three: a **Hypothesis Ranking** section, an
**Evidence Gaps and Uncertainty** section, and a **Human Review Decisions**
section. The frontend exposes them on the conflict detail page (ranking + review
actions) and a dedicated **Audit Trail** page.

### Investigation report

`services/report_service.py` assembles a report **only from persisted records**
and returns three views of the same data: a flat `sections` list, the markdown
export, and a versioned `json_data` document (`schema_version: 2`) that the UI
renders. The report covers investigation id and question, documents, claims,
conflicts, evidence *for* and *against* each conflict-relevant claim, competing
hypotheses, verification results, the conclusion or inconclusive status,
confidence and its interpretation, missing evidence and unresolved questions,
human-review status, an agent-activity summary, limitations/timestamps and the
audit trail.

Explainability guarantees:

* **Source traceability.** Every document, claim, conflict and evidence item
  carries its database id and a UI link; the report never cites a record that is
  not stored. This is asserted by `tests/test_reports.py`.
* **Observed vs inferred.** Documents, claims, conflicts and document/user
  evidence are labelled `observed`; hypotheses and inferred evidence are
  `inferred`.
* **No fabrication.** Contradicting evidence is only ever the evidence recorded
  against the opposing claim in a stored conflict — contradictions are never
  inferred beyond what the blackboard asserts.
* **Escaping and privacy.** Untrusted text is control-stripped for every
  artifact and HTML-escaped in the markdown/PDF exports; storage filenames and
  checksums are never emitted.

`services/report_pdf.py` renders the sections to a paginated A4 PDF using
**PyMuPDF** (already a dependency, used for extraction), so PDF export requires no
new package and interprets no HTML. The Reports page (`frontend`) renders the
structured document with source links, an observed/inferred distinction, a
print-optimised layout and Print / PDF / Markdown / JSON actions.

## 13. Dashboard and blackboard snapshot

The Overview dashboard is driven entirely by `GET /api/blackboard/snapshot`,
which reads persisted rows — nothing is simulated. The snapshot returns the
current `counts`, the blackboard graph, recent agent activity, a severity
distribution and an activity timeline.

The activity timeline is parameterised by a `days` window (default `14`, clamped
to `1–365`), selectable in the UI (7 / 14 / 30 / 90 days). The snapshot also
returns four enum distributions, each listing **every known value** (including
zero counts) so the UI can render a stable, complete breakdown:

- `conflict_type_distribution`
- `conflict_status_distribution`
- `investigation_status_distribution`
- `evidence_verification_distribution`

Each distribution entry is `{ "value": <enum>, "count": <int> }`. The dashboard
renders them as clickable cards that deep-link into the corresponding list page
with the filter pre-applied via URL query parameters — for example
`/conflicts?type=numerical_disagreement`, `/conflicts?status=open`,
`/investigations?status=running` and `/evidence?verification_status=verified`.
The list pages (Conflicts, Evidence, Investigations) initialise their filter
state from those query parameters.

---

## 14. Knowledge graph

The knowledge graph is a **read-only projection** of the persisted blackboard, not
a second store. `services/knowledge_graph_service.py::build_knowledge_graph`
reads the same records the agents reason over and returns typed nodes
(`document`, `claim`, `evidence`, `conflict`, `hypothesis`, `conclusion`,
`agent`, `investigation`) and typed edges. Nothing is invented: every node is a
stored row or a registered agent, and every edge is backed by a persisted
foreign key, an association row (`investigation_conflicts`), a JSON id list on a
record, or an agent execution-ledger / event-log row.

Edges carry a `verified` flag so the UI can distinguish a direct persisted link
(claim `document_id`, conflict `claim_a_id`/`claim_b_id`, evidence
`supports_hypothesis_id`, an agent's recorded output) from an **inferred** one
derived from a JSON id list or a membership join (a hypothesis'
`supporting_evidence_ids`, a conclusion's `supporting_evidence_ids`, a
hypothesis' investigation membership).

The required relationship vocabulary is `contains`, `supported_by`,
`contradicts`, `supports`, `challenges`, `investigated_in`, `created`,
`derived_from`; structural connectors (`concerns`, `explains`, `gathered_for`,
`investigates`, `concludes`) are added so conflict and investigation nodes stay
connected. "Created" edges come from the event log and the execution ledger, so
each agent is linked to the records it actually produced.

`GET /api/knowledge-graph` exposes it with investigation / record-type /
relationship filters and node+edge caps (`truncated` reports the full totals).
The frontend **Knowledge Graph** page (`pages/KnowledgeGraph.tsx`) renders it
with React Flow: filters with live counts, a verified (solid) vs inferred
(dashed) legend, a node inspector that reuses the blackboard trace endpoint, and
an evidence-path highlight that walks backward from a selected conclusion over
the reasoning edges.
