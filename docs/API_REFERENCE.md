# NeuroSync — API Reference

Base path: **`/api`**. Interactive documentation is available at `/docs`
(Swagger UI) and `/redoc`. All request/response bodies are JSON unless noted.
List endpoints return a paginated envelope:

```json
{ "items": [ ... ], "total": 42, "page": 1, "page_size": 50 }
```

Errors return `{ "detail": "...", "code": "..." }`.

---

## Health & configuration

| Method | Path           | Description                                        |
| ------ | -------------- | -------------------------------------------------- |
| GET    | `/api/health`  | Status, version, and whether AI is configured.     |
| GET    | `/api/config`  | Public configuration: mode, upload limit, weights. |
| GET    | `/api/settings/reasoning` | Current reasoning-mode preference and effective mode. |
| PUT    | `/api/settings/reasoning` | Set the reasoning mode (`deterministic` \| `ai_assisted`). |

`GET /api/health` includes `reasoning_mode` (the stored preference) and
`effective_mode` (what is actually running — degrades to `deterministic` when no
provider is configured). `ai_configured` is true only when a key is present *and*
`ENABLE_LLM=true`.

`GET /api/config` returns the scheduler weights and limits, including the
orchestration safeguards `agent_max_retries`, `max_agent_executions` and
`max_attempts_per_action` (see `docs/orchestration.md`).

### Reasoning settings

```json
{
  "reasoning_mode": "ai_assisted",
  "effective_mode": "deterministic",
  "llm_configured": false,
  "model": "gpt-4o-mini",
  "provider": "openai",
  "available_modes": ["deterministic", "ai_assisted"],
  "note": "AI-assisted mode selected, but no provider is configured. Running deterministically."
}
```

Request body: `{ "mode": "deterministic" | "ai_assisted" }`. The preference is a
global, persisted setting. Selecting `ai_assisted` without a configured provider
is accepted but `effective_mode` stays `deterministic` and `note` explains why.
Per-investigation `enable_llm` is ANDed with the global mode as an opt-out.

---

## Documents

| Method | Path                              | Description                              |
| ------ | --------------------------------- | ---------------------------------------- |
| POST   | `/api/documents/upload`           | Upload one or more files (multipart `files`). Claims are extracted immediately. |
| GET    | `/api/documents`                  | List documents (`page`, `page_size`).    |
| GET    | `/api/documents/{id}`             | Document detail incl. text preview.      |
| GET    | `/api/documents/{id}/credibility` | Sources credibility assessment (see below). |
| POST   | `/api/documents/{id}/reprocess`   | Re-extract text and claims.              |
| DELETE | `/api/documents/{id}`             | Delete a document and its derived data.  |

Accepted types: `.txt`, `.md`, `.csv`, `.json`, `.pdf`, `.docx`.

**Upload response** (array, one entry per file):

```json
{
  "id": 1,
  "filename": "report.txt",
  "status": "processed",
  "message": "Uploaded and processed.",
  "claim_count": 2,
  "conflict_count": 0,
  "duplicate": false
}
```

---

## Claims

| Method | Path                  | Description                                              |
| ------ | --------------------- | -------------------------------------------------------- |
| GET    | `/api/claims`         | List claims. Filters: `document_id`, `subject`, `claim_type`, `q`. |
| GET    | `/api/claims/{id}`    | A single claim.                                          |

A claim exposes `subject`, `predicate`, `object_value`, `numeric_value`, `unit`,
`polarity`, `claim_type`, `timestamp_value`, `source_reference` and `confidence`.

---

## Conflicts

| Method | Path                    | Description                                            |
| ------ | ----------------------- | ------------------------------------------------------ |
| GET    | `/api/conflicts`        | List conflicts. Filters: `severity`, `conflict_type`, `status`, `document_id`, `min_confidence`, `max_confidence`, `q`. |
| GET    | `/api/conflicts/{id}`   | Full detail: both claims, evidence, hypotheses, conclusion, related investigations, and `why_flagged`. |
| GET    | `/api/conflicts/{id}/hypotheses/ranking` | Ranked explanations with transparent criteria (see below). |
| GET    | `/api/conflicts/{id}/evidence-gaps`      | Consolidated list of missing information blocking resolution. |
| GET    | `/api/conflicts/{id}/reviews`            | Human review decisions recorded against this conflict. |
| PATCH  | `/api/conflicts/{id}`   | Update `status`, `severity` or `resolution_summary`.   |

Conflict types: `direct_contradiction`, `numerical_disagreement`,
`temporal_inconsistency`, `source_disagreement`, `missing_context`,
`semantic_inconsistency`.
Statuses: `open`, `investigating`, `resolved`, `inconclusive`, `human_review`.

### Hypothesis ranking

`GET /api/conflicts/{id}/hypotheses/ranking` returns the competing hypotheses
ordered by documented evidence weight (highest first), each with:

```json
{
  "hypothesis_id": 1, "rank": 1, "title": "Sensor or measurement-source issue",
  "support_score": 0.724, "confidence": 0.679,
  "confidence_caveat": "Bounded support indicator derived from evidence weights; NOT a statistically calibrated probability.",
  "criteria": {
    "supporting_evidence_weight": 0.812, "contradicting_evidence_weight": 0.0,
    "distinct_supporting_sources": 1, "has_direct_supporting_evidence": true,
    "supporting_evidence_count": 1, "contradicting_evidence_count": 0
  },
  "supporting_evidence": [ { "id": 1, "evidence_type": "calibration_record", "weight": 0.476, "document_filename": "Maintenance_Log_C.txt" } ],
  "contradicting_evidence": [],
  "assumptions": ["..."], "missing_information": ["..."],
  "margin_to_next": 0.224
}
```

Scores are **bounded support indicators**, never calibrated probabilities.

---

## Evidence

| Method | Path                              | Description                                   |
| ------ | --------------------------------- | --------------------------------------------- |
| GET    | `/api/conflicts/{id}/evidence`    | Evidence for a conflict.                      |
| POST   | `/api/conflicts/{id}/evidence`    | Add user-supplied evidence.                   |
| GET    | `/api/evidence`                   | Global list. Filters: `conflict_id`, `origin`, `evidence_type`, `verification_status`, `q`. |

Every evidence item (`EvidenceOut`) includes an `assessment` object computed by
`services/assessment_service.py`:

```json
{
  "assessment": {
    "factors": {
      "relevance": { "value": 0.71, "label": "high", "explanation": "..." },
      "provenance": { "value": 0.85, "label": "strong", "explanation": "..." },
      "recency": { "value": 0.8, "label": "recent", "explanation": "..." },
      "completeness": { "value": 0.6, "label": "partial", "explanation": "..." },
      "corroboration": { "value": 0.5, "label": "moderate", "explanation": "..." },
      "contradictory_evidence": { "value": 0.0, "label": "none", "explanation": "..." }
    },
    "source_reliability": { "label": "unknown", "heuristic_indicator": 0.6, "note": "..." },
    "overall_score": 0.68,
    "overall_label": "moderate",
    "missing_information": ["No explicit unit ..."],
    "formula": "0.35*relevance + 0.25*provenance + 0.15*recency + 0.15*completeness + 0.10*corroboration (x0.85 if contradictory evidence)",
    "caveat": "Bounded support indicator, not a calibrated probability."
  }
}
```

The score is a bounded support indicator; `source_reliability.label` is
explicitly `"unknown"` when the source cannot be judged.

Add-evidence body:

```json
{
  "description": "Independent sensor log confirms recalibration at 10:00.",
  "evidence_type": "calibration_record",
  "source_reference": "Sensor log 2024-03-11",
  "relevance_score": 0.8,
  "reliability_score": 0.85,
  "supports_hypothesis_id": 2,
  "contradicts_hypothesis_id": null
}
```

---

## Fact verification

Claim-level, evidence-grounded verification. Every result is computed on read
from the claims, evidence and document text already stored; nothing is fetched
from an external source and no evidence is invented.

| Method | Path                                        | Description                                    |
| ------ | ------------------------------------------- | ---------------------------------------------- |
| GET    | `/api/claims/{id}/verification`             | Verify one claim. Optional `use_llm=true`.     |
| GET    | `/api/verification/claims`                  | Verify every claim. Filters: `document_id`, `claim_type`, `verdict`, `q`. |
| GET    | `/api/verification/summary`                 | Verdict counts for the same filters.           |
| GET    | `/api/investigations/{id}/claim-verifications` | Verify claims using only that investigation's documents. |

Verdicts: `supported`, `contradicted`, `partially_supported`, `unverified`.
Only a different document or user-supplied evidence counts as independent
corroboration, so a claim is never "supported" merely by its own source. When
there is insufficient evidence the verdict is `unverified`, with the missing
information listed. `use_llm=true` adds a model-written rationale but cannot
change the verdict; citations that do not resolve to a stored record are
rejected wholesale.

Each result includes the claim, verdict, confidence, summary, explanation,
supporting/contradicting/neutral evidence items (each with document, page or
character location, snippet and link), `missing_information`, the analysis
method and an explicit caveat.

---

## Source credibility

Assesses each stored source on six factors. Like fact verification, it is
computed on read from stored records and never invents credentials or scores.

| Method | Path                                            | Description                                      |
| ------ | ----------------------------------------------- | ------------------------------------------------ |
| GET    | `/api/documents/{id}/credibility`               | Full six-factor assessment for one source.       |
| GET    | `/api/source-credibility`                       | Global list. Filters: `q`, `level`, `unknown_only`, `document_id`. |
| GET    | `/api/investigations/{id}/source-credibility`   | The same assessment scoped to an investigation.  |

Factors:

| Key | What is checked |
| --- | --------------- |
| `authenticity` | Checksum, stored file presence, recorded size, processing status and extracted content. |
| `author` | Author/creator and organization values in `source_metadata`. Never inferred from the filename or text. |
| `publication_date` | A date recorded in `source_metadata`, parsed without guessing. The upload time is never used. |
| `evidence_quality` | Extracted text, structured claims, linked evidence, primary evidence types and recorded directness. |
| `traceability` | Checksum, retrievable file, page/character map and per-claim/evidence source references. |
| `consistency` | The source's claims compared with the other stored documents using the fact-verification engine. Same-source restatements never count as agreement. |

Levels: `well_documented`, `partially_documented`, `limited_documentation`,
`unverifiable`.

A factor that cannot be assessed has `score: null` and status `unknown`; it is
excluded from the aggregate rather than scored as zero. If less than 40% of the
weighted checklist is assessable, no aggregate is shown and the source is
labelled `unverifiable`. The response always includes the recorded metadata, the
factors' inputs and missing information, warnings, a methodology string and an
explicit caveat. `unknown_only=true` returns sources whose identity is unknown
(no author and no organization) or which are unverifiable.

---

## Investigation chat

A deterministic question-answering layer over one investigation's stored rows
(documents, claims, conflicts, evidence, hypotheses and conclusions). It is not
a language model: every sentence is assembled from a stored field, so it cannot
produce an unsupported answer. No record from another investigation is ever
consulted.

| Method | Path                                             | Description                                         |
| ------ | ------------------------------------------------ | --------------------------------------------------- |
| POST   | `/api/investigations/{id}/chat`                  | Ask one question about the investigation.           |
| GET    | `/api/investigations/{id}/chat/suggestions`      | Example questions the current records can answer.   |

**Request body**

```json
{
  "question": "Which document supports this claim?",
  "claim_id": 4
}
```

`question` is required (1–2000 characters, trimmed). The optional `conflict_id`,
`claim_id`, `hypothesis_id` and `document_id` fields disambiguate words like
"this conflict" or "this claim". They only select a record that is already linked
to the investigation; an id from another investigation is rejected with a plain
message rather than answered.

**Response**

`ChatAnswerOut` includes:

| Field | Meaning |
| ----- | ------- |
| `intent` | Detected question type: `conflict_detected`, `claim_support`, `hypothesis_contradiction`, `investigation_inconclusive`, `missing_evidence`, `summary`, `document_lookup` or `record_search`. |
| `answer` | The storable assembled text, with `[n]` markers matching `citations[].number`. |
| `insufficient_information` | `true` when the stored records cannot fully answer. |
| `missing_information` | The specific gaps, quoted from stored `missing_information`/`unresolved_questions` fields or the verifier. |
| `citations` | Numbered references: `kind`, `record_id`, `label`, `document_id`, `document_filename`, `page`, `char_start`, `char_end`, `text_location`, `snippet`, `link`. |
| `follow_up_questions` | Questions that the current records can answer. |
| `data_sources` | Row counts the answer drew on. |
| `methodology`, `caveat`, `analyzed_at` | How the answer was built and its limits. |

The five supported question shapes are:

- **Why was this conflict detected?** — quotes the stored conflict type, severity,
  detector explanation, detection metadata, both compared claims and any attached
  evidence rows.
- **Which document supports this claim?** — runs the fact verifier for the claim
  and distinguishes independent corroboration from same-source restatements;
  reports contradicting sources too.
- **What evidence contradicts this hypothesis?** — lists the stored evidence rows
  linked to the hypothesis and its recorded assumptions and missing information.
- **Why is the investigation inconclusive?** — quotes the latest conclusion's
  `decision_type`, text, unresolved questions and limitations.
- **What additional evidence is required?** — collects recorded gaps from
  hypotheses, conclusions, missing evidence rows, conflicts without evidence and
  the verifier's per-claim `missing_information`.

Every factual answer cites at least one stored record. If no record can support
an answer, the response sets `insufficient_information: true` and says so instead
of guessing. Answers resolve citations to a document and page or character
location through the same helpers as fact verification, so links open
`/documents/{id}`.

---

## Hypotheses

| Method | Path                                | Description                                  |
| ------ | ----------------------------------- | -------------------------------------------- |
| GET    | `/api/conflicts/{id}/hypotheses`    | Hypotheses for a conflict.                   |
| POST   | `/api/conflicts/{id}/hypotheses`    | Add a user-authored hypothesis.              |
| GET    | `/api/hypotheses`                   | Global list. Filters: `conflict_id`, `status`, `q`. |
| PATCH  | `/api/hypotheses/{id}`              | Record a review action.                      |

Review body: `{ "action": "flag_for_investigation" | "human_review", "note": "" }`.

---

## Human review

Records an explicit human decision on a conclusion. The decision is timestamped,
attributed, written to the audit trail, announced on the investigation's event
stream, and updates the corresponding conflict status.

| Method | Path                                      | Description                                   |
| ------ | ----------------------------------------- | --------------------------------------------- |
| POST   | `/api/conclusions/{id}/review`            | Record a decision on a conclusion.            |
| GET    | `/api/conclusions/{id}/reviews`           | Review history for a conclusion.              |
| GET    | `/api/conflicts/{id}/reviews`             | Review history for a conflict.                |
| GET    | `/api/reviews`                            | Global list. Filter: `investigation_id`.      |

Request body:

```json
{ "decision": "approved", "reviewer": "Dr. Rao", "note": "Evidence is consistent." }
```

Decisions: `approved` (conflict → `resolved`), `rejected` (conflict → `open`),
`inconclusive` (conflict → `inconclusive`),
`request_more_investigation` (conflict → `human_review`), `reopen`
(conflict → `open`). Every review is a local, manual review; the response's
`review_kind` is `"local_manual_review"`.

Response:

```json
{
  "review": { "id": 1, "conclusion_id": 1, "decision": "approved", "reviewer": "Dr. Rao", "previous_decision_type": "human_review_required", "review_kind": "local_manual_review" },
  "conflict_status": "resolved",
  "conclusion_decision_type": "human_review_required",
  "message": "Conclusion approved; conflict marked resolved."
}
```

---

## Audit trail

| Method | Path          | Description                                                        |
| ------ | ------------- | ------------------------------------------------------------------ |
| GET    | `/api/audit`  | Append-only history of blackboard changes. Filters: `entity_type` (`claim`, `evidence`, `hypothesis`, `conflict`, `conclusion`, `human_review`), `entity_id`, `investigation_id`, `conflict_id`. |

Each entry records `actor` (`"agent"` or the reviewer's name), `action`, a
human-readable `summary`, a structured `detail` object and a timestamp.

---

## Investigations

| Method | Path                                     | Description                              |
| ------ | ---------------------------------------- | ---------------------------------------- |
| POST   | `/api/investigations`                    | Create an investigation.                 |
| GET    | `/api/investigations`                    | List (`status` filter).                  |
| GET    | `/api/investigations/{id}`               | Current state and progress.              |
| PATCH  | `/api/investigations/{id}`               | Update name/question/limits (not while running). |
| POST   | `/api/investigations/{id}/start`         | Start (runs in the background).          |
| POST   | `/api/investigations/{id}/pause`         | Pause.                                   |
| POST   | `/api/investigations/{id}/resume`        | Resume.                                  |
| POST   | `/api/investigations/{id}/cancel`        | Cancel.                                  |
| GET    | `/api/investigations/{id}/activity`      | Ordered agent activity log.              |
| GET    | `/api/investigations/{id}/report`        | Structured, explainable report object.   |
| GET    | `/api/investigations/{id}/report/export` | Export as `?format=markdown`, `json` or `pdf`. |
| GET    | `/api/investigations/{id}/events`        | **SSE** stream of events.                |

Create body:

```json
{
  "name": "Resolve temperature conflict",
  "research_question": "Why do the reports disagree?",
  "document_ids": [1, 2, 3],
  "conflict_ids": [],
  "iteration_limit": 25,
  "min_evidence_threshold": 1,
  "enable_llm": true
}
```

Provide at least one `document_id` or `conflict_id`. `enable_llm` is an opt-out:
the investigation only uses AI assistance when it is `true` **and** the global
reasoning mode is `ai_assisted` **and** a provider is configured.

### Activity log entries

`GET /api/investigations/{id}/activity` returns one entry per agent execution
(retries are separate entries). In addition to `agent_name`, `action`, `status`
and `output_summary`, each entry carries orchestration fields:

```json
{
  "sequence": 7,
  "attempt": 2,
  "status": "success",
  "input_record_ids": [3],
  "output_record_ids": [11, 12],
  "error": "",
  "state_summary": "evidence=2 (unverified=0, missing=0); unresolved_conflicts=1; ..."
}
```

`attempt` is `1` for a first try and greater than `1` for a retry; `error` is
populated when `status` is `failed`; `state_summary` is the blackboard state the
scheduler used to choose the action.

### Server-Sent Events

The live progress stream is reliability-oriented:

* Event-log frames carry the event's database id as the SSE `id`, so
  `EventSource` reconnection resumes via the `Last-Event-ID` header without
  replaying already-delivered events.
* A `progress` frame with **actual backend state** (status, current agent and
  objective, iteration counts, completed/failed/skipped execution tallies,
  conflict totals) is emitted on connect and whenever the state changes - nothing
  is simulated.
* Event payloads are **redacted** before they leave the server: raw claim and
  document text is removed (and recorded under `redacted_fields`). Identifiers
  and structured metadata are preserved. The stored log keeps full payloads for
  the audit trail.
* An unknown investigation emits `event: stream_error`. A terminal
  investigation drains, then emits `event: stream_end` and closes.

Frames look like:

```
id: 42
event: conflict_detected
data: {"id":42,"investigation_id":1,"event_type":"conflict_detected","agent_name":"Conflict Detector","payload":{...},"created_at":"..."}
```

```
event: progress
data: {"status":"running","current_agent":"Investigator","iteration_count":4,"iteration_limit":25,"completed":4,"failed":0,...}
```

Event types: `investigation_started`, `agent_selected`, `document_processed`,
`claim_extracted`, `conflict_detected`, `hypothesis_generated`,
`evidence_evaluated`, `hypothesis_verified`, `conclusion_reached`,
`iteration_completed`, `investigation_paused`, `investigation_resumed`,
`investigation_completed`, `investigation_cancelled`,
`human_review_requested`, plus the control frames `progress`, `stream_end` and
`stream_error`.

---

## Reports

`GET /api/investigations/{id}/report` returns a report built entirely from
persisted records. Its `json_data` is a versioned (`schema_version: 2`),
self-describing document used by the UI, and `sections` is a flat
heading/body/items view used by the markdown and PDF exports.

Each report covers: investigation title and identifier, question, documents,
claims, conflicts, evidence *for* and *against* each conflict-relevant claim,
competing hypotheses, verification results, the final conclusion or
inconclusive status, confidence and its interpretation, missing
evidence / unresolved questions, human-review status, agent-activity summary,
limitations and timestamps, and the audit trail.

Guarantees:

* **Traceability.** Every document, claim, conflict and evidence item carries
  its database id and a UI link (`/documents/{id}`, `/conflicts/{id}`); the
  report never cites a record that is not stored.
* **Observed vs inferred.** Claims, conflicts and document/user evidence are
  labelled `observed`; hypotheses and inferred evidence are labelled `inferred`.
* **No fabrication.** Contradicting evidence is only ever the evidence recorded
  against the opposing claim in a stored conflict.
* **Escaping.** Markdown and PDF exports HTML-escape untrusted text; storage
  filenames and checksums are never emitted.

Export: `GET /api/investigations/{id}/report/export?format=markdown|json|pdf`.
The PDF is rendered with PyMuPDF (already a dependency) and returned as
`application/pdf` with an attachment filename.

---

## Evaluation & performance

The evaluation API stores human-labelled test cases and the **raw per-case
outcomes** of each run. Metrics are always recomputed from those persisted rows;
no endpoint accepts a pre-computed score. A detected conflict is only counted
correct when a ground-truth label says so.

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET    | `/api/evaluation/datasets` | List built-in reference benchmarks and user-labelled test sets. |
| POST   | `/api/evaluation/datasets` | Create a labelled test set (JSON body). |
| POST   | `/api/evaluation/datasets/upload` | Upload the same JSON shape as a file (multipart `file`, max 5 MB). |
| GET    | `/api/evaluation/datasets/{id}` | Dataset detail with every labelled case and its ground truth. |
| DELETE | `/api/evaluation/datasets/{id}` | Delete a **user** test set and its runs (built-ins return `400`). |
| POST   | `/api/evaluation/datasets/{id}/run` | Execute the dataset through the production pipeline and persist every outcome. |
| GET    | `/api/evaluation/runs` | Run history. Filters: `dataset_id`, `kind`, `status`, `limit`. |
| GET    | `/api/evaluation/runs/{id}` | Full run: metrics, confusion data, failures and per-case results. |
| GET    | `/api/evaluation/runs/{id}/export?format=csv\|pdf` | Export a **completed** run (failed runs return `409`). |
| GET    | `/api/evaluation/dashboard` | Headline runs, datasets, live agent performance and document analytics. |
| GET    | `/api/evaluation/analytics/agents` | Agent execution statistics only. |
| GET    | `/api/evaluation/analytics/documents` | Document/investigation analytics only. |

Create/upload body. `kind` selects the evaluation type. Conflict cases supply
`text_a`/`text_b`; evidence-verification cases supply `claim_text` plus one or
more comparison `documents`. `expected` is mandatory human ground truth.

```json
{
  "name": "Temperature checks",
  "kind": "conflict_detection",
  "version": "1.0.0",
  "cases": [
    {
      "case_key": "units-temp",
      "category": "units",
      "text_a": "The temperature was 100°F at 10:00 AM.",
      "text_b": "The temperature was 40°C at 10:00 AM.",
      "expected": {
        "label": true,
        "expected_flagged": true,
        "expected_types": ["numerical_disagreement"]
      },
      "rationale": "100°F is 37.8°C, beyond the comparison tolerance."
    }
  ]
}
```

Evidence case expectation: `{"verdict": "supported" | "contradicted" | "partially_supported" | "unverified"}`.

Run `metrics` are kind-specific:

* `conflict_detection`: `{ "overall": { "counts": {"tp","fp","fn","tn"}, "precision", "recall", "f1", "accuracy", "false_positive_rate", "false_negative_rate", ... }, "signals": {...}, "dataset": {...} }`.
* `evidence_verification`: `{ "overall": { "labels", "total", "correct", "accuracy", "macro_precision", "macro_recall", "macro_f1", "per_class", "confusion" }, "dataset": {...} }`.

Undefined rates are `null` (rendered `n/a`), never `0`. `provenance` is
`reference_labelled` for shipped benchmarks and `user_labelled` for created or
uploaded test sets. Reference benchmarks are curated fixtures, not independently
audited field trials. Evaluation documents are materialised only in a throwaway
in-memory database, so runs never touch real documents, uploads or blackboard
records.

---

## Blackboard

| Method | Path                        | Description                                                |
| ------ | --------------------------- | ---------------------------------------------------------- |
| GET    | `/api/blackboard`           | Current `{ counts, graph }` of the blackboard.             |
| GET    | `/api/blackboard/snapshot`  | Full snapshot: counts, graph, recent activity, severity distribution, an activity timeline, and four enum distributions. |

The snapshot accepts an optional `days` query parameter (default `14`, range
`1–365`) controlling the activity-timeline window; the response echoes it as
`window_days`. In addition to `severity_distribution` and `activity_timeline`,
it returns four distributions — `conflict_type_distribution`,
`conflict_status_distribution`, `investigation_status_distribution` and
`evidence_verification_distribution` — each a list of
`{ "value": <enum>, "count": <int> }` covering **every known value** (including
zero counts).

Graph nodes use `node_type` in `{document, claim, conflict, evidence, hypothesis,
conclusion}`; edges use `edge_type` in `{extracted_from, contradicts, supports,
refutes, derived_from, resolved_by}`.

---

## Knowledge graph

| Method | Path                       | Description                                                |
| ------ | -------------------------- | ---------------------------------------------------------- |
| GET    | `/api/knowledge-graph`     | Typed, filterable projection of the blackboard plus the agents and investigations that produced it. |

Params: `investigation_id` (scope to one investigation), repeatable
`record_type` (node-type filter) and `relation_type` (edge-type filter),
`max_nodes` (default 800) and `max_edges` (default 2500).

Node types: `document`, `claim`, `evidence`, `conflict`, `hypothesis`,
`conclusion`, `agent`, `investigation`.

Edge types include the required set `contains`, `supported_by`, `contradicts`,
`supports`, `challenges`, `investigated_in`, `created`, `derived_from` plus the
structural connectors `concerns`, `explains`, `gathered_for`, `investigates`,
`concludes`.

Every edge carries `verified`: `true` when the link is a direct persisted
foreign key, association row or agent execution/event-ledger row; `false` when
it is derived from a persisted JSON id list or a membership join (for example
`derived_from` from a conclusion's `supporting_evidence_ids`). The response also
returns node/relation counts, `totals` (pre-cap), and `truncated`. Node details
reuse `GET /api/blackboard/trace/{record_type}/{record_id}`.

---

## Agents

| Method | Path            | Description                                                        |
| ------ | --------------- | ------------------------------------------------------------------ |
| GET    | `/api/agents`   | Status, responsibility, completed tasks, last result, and declared contract (`required_inputs`, `expected_outputs`, `run_conditions`, `stop_conditions`) for each of the six agents. |

---

## Demo

| Method | Path                    | Description                                             |
| ------ | ----------------------- | ------------------------------------------------------- |
| POST   | `/api/demo/load`        | Load the labelled demonstration scenario (`?auto_start=true` to run immediately). |
| POST   | `/api/demo/reset`       | Remove all demonstration documents and investigations.  |

---

## Search

| Method | Path                                 | Description                                        |
| ------ | ------------------------------------ | -------------------------------------------------- |
| GET    | `/api/search`                        | Search across documents, claims, conflicts, evidence, hypotheses and investigations. Params: `q` (required), `limit`. |

Response groups results by entity type:

```json
{
  "query": "temperature",
  "documents": [{ "id": 1, "label": "Inspection_Report_A.txt" }],
  "claims": [{ "id": 1, "label": "Machine M-17 reached a temperature of 92°C at 10:00 AM." }],
  "conflicts": [], "evidence": [], "hypotheses": [], "investigations": []
}
```
