# NeuroSync — User Guide

A practical walkthrough of the application: what each page does, how to run an
investigation, how to read the results, and what the system's limitations are.

---

## 1. What NeuroSync does

You give it documents. It reads them, pulls out factual and measurable
statements, and looks for places where those statements disagree. Then a team of
software agents investigates each disagreement — gathering more evidence,
proposing explanations, weighing the evidence, and deciding whether a defensible
answer can be reached. Everything is shown transparently, with reasons.

---

## 2. Getting started

1. Start the backend and frontend (see the README).
2. Open `http://localhost:5173`.
3. On **Overview**, click **Load demo** to explore immediately, or go to
   **Documents** to upload your own files.

The demo scenario is the *Machine M-17 Temperature Disagreement Investigation*:
three records about one machine that disagree about the temperature reading.

---

## 3. The demo scenario

| Record              | Says                                                          |
| ------------------- | ------------------------------------------------------------- |
| Inspection Report A | Machine M-17 reached **92 °C** during inspection at 10:00 AM  |
| Inspection Report B | Machine M-17 reached **76 °C** during inspection at 10:00 AM  |
| Maintenance Log C   | The temperature **sensor was recalibrated at 10:30 AM**       |

What you should see the system discover:

- A single **numerical disagreement** about M-17's temperature at the *same*
  time (10:00 AM) — the two readings cannot both be correct as stated.
- Several **competing explanations** for the disagreement (for example, a sensor
  or measurement-source issue, a transcription error, a genuine difference, or
  missing context). None is treated as proven by the disagreement alone.
- The **recalibration** in Log C is treated as *contextual evidence*, not proof:
  it is relevant to a sensor problem but does not by itself establish that the
  sensor was faulty at 10:00 AM.

Because the disagreement cannot be resolved automatically from the available
documents, the system **escalates the conflict for human review** rather than
asserting a cause. That is the correct outcome, not a failure.

---

## 4. Pages

### Overview
Live dashboard: blackboard counts, conflict-severity chart, a 14-day activity
timeline, and the most recent agent actions. **Load demo** and **New
investigation** begin here.

### Documents
Upload (drag-and-drop or browse), list, view, reprocess and delete documents.
Each row shows status, extracted claim count and conflict count. Open a document
to read its extracted text and the structured claims found in it.

### Conflicts
The heart of the analysis. Filter by severity, status, type or text. Each entry
shows both sides, how many evidence items and hypotheses it has, and the current
confidence. Click one to open its detail page.

### Conflict detail
- **Why this was flagged** — a plain-language rationale for the detection.
- **Claim A vs Claim B** — the two opposing statements, side by side, with
  subject, value, type, time and confidence.
- **Evidence** — every supporting/contradicting item with provenance and scores.
- **Hypotheses** — competing explanations with support bars and status.
- **Hypothesis ranking** — the competing explanations ordered by documented
  evidence weight, each showing its supporting and contradicting evidence, the
  number of distinct sources, whether it has direct evidence, and the margin to
  the next explanation. Scores are bounded support indicators, **not** calibrated
  probabilities.
- **Conclusion** — the Decision Agent's assessment, confidence, the supporting
  evidence it cites, and unresolved questions.
- **Human review** — approve, reject or request more investigation on the
  conclusion. The conflict status updates accordingly, the decision is
  attributed and timestamped, and it appears in the audit trail.
- **Investigate** — spin up a focused investigation for this conflict.
- Manual review actions to mark it resolved, inconclusive or escalate to human
  review.

### Blackboard
A live graph of the knowledge store: documents → claims → conflicts → evidence →
hypotheses → conclusions. Red edges are contradictions, green support, purple
resolution. Click a document or conflict node to jump to it.

### Agents
The six agents, their responsibilities, current status (idle, running,
completed), tasks completed and last result.

### Hypotheses
All hypotheses across conflicts, filterable by status, showing support scores,
supporting/contradicting evidence counts and missing information. Use **Flag** to
mark one for further investigation, or **Mark human-reviewed** to record a human
decision explicitly.

### Evidence
Every evidence item with its origin (document/user/inferred), type, verification
state, reliability/relevance/directness and source.

### Investigations
Create and run investigations. Choose documents and/or conflicts, set an
iteration limit and a minimum-evidence threshold, then **Create & start**. The
list shows progress, counts and stop reason.

### Investigation workspace
The live cockpit. It shows the current agent and objective, iteration progress,
conflicts resolved, evidence and conclusions, plus:
- an **agent activity timeline** (each action, its result and *why* it was taken), and
- a **live event stream** fed by server-sent events.

Use **Pause**, **Resume** and **Cancel** at any time.

### Reports
Pick an investigation to view its structured report: title, objective, confidence
and a confidence explanation, then sections for each finding, including a
**Hypothesis Ranking**, an **Evidence Gaps and Uncertainty** list and a
**Human Review Decisions** log. Export as **Markdown** or **JSON**.

### Audit trail
A timestamped, attributed, append-only record of every change to the blackboard —
claims extracted, evidence created, hypotheses proposed and verified, conflicts
detected, conclusions reached and human review decisions. Filter by entity type.

### Settings
**Reasoning mode** (Deterministic or AI-assisted), engine and provider details,
the scheduler weights, and demonstration-data controls (load / reset). The app is
fully functional without an API key.

#### Choosing a reasoning mode

- **Deterministic** (default) — rule-based reasoning only. Reproducible and
  requires no credentials.
- **AI-assisted** — the agents may additionally use a configured language model to
  extract claims, propose hypotheses, interpret evidence and write explanations.

If you select AI-assisted but the backend has no provider configured, NeuroSync
does **not** fail: it keeps running deterministically and tells you so. To make AI
assistance actually active, set `ENABLE_LLM=true` and `OPENAI_API_KEY` in the
backend environment and restart the server (see the README). When AI is active,
its suggestions are labelled and every quote/citation is checked against the
documents and evidence — ungrounded output is discarded. Toggling modes never
changes your documents or existing results.

---

## 5. Running your own investigation

1. **Upload documents** on the Documents page — ideally two or more sources that
   cover the same subjects so the Conflict Detector has something to compare.
2. The upload extracts claims automatically. Open **Conflicts** to see what was
   detected. (If the system finds nothing, the documents may not contain directly
   comparable statements.)
3. On **Investigations**, click **New investigation**; select the documents (and
   optionally specific conflicts); set limits; **Create & start**.
4. Watch the **workspace** as agents work. The system stops when there is nothing
   useful left to do, the iteration limit is reached, or you cancel it.
5. Read the result on **Reports**, and inspect the reasoning on the conflict page.

---

## 6. How to read the numbers

- **Confidence / support scores** are *bounded support indicators* (0–1), not
  calibrated probabilities. A 0.78 means "well supported by the available
  evidence", not "78% likely to be true".
- **Priority** (0–100) is the scheduler's estimate of how valuable the next action
  is, from severity, uncertainty, evidence gaps and expected information gain.
- A **supported** conclusion requires strong, direct, multi-source support.
  Anything weaker is reported as *tentative*, *inconclusive* or *human review
  required*.
- **Inconclusive is a valid outcome.** The system deliberately avoids forcing
  answers when the evidence does not justify one.

---

## 7. Limitations

- Extraction is rule-based: it reliably captures measurements, presence/absence
  statements and times, but will not understand every nuance of free-form text.
- Conflict detection only compares claims that share a subject across different
  documents; it does not attempt deep semantic reasoning.
- Scores are heuristic indicators, not statistical probabilities.
- Only information present in the uploaded documents (plus any evidence you add
  manually) is considered.
- The optional LLM, when enabled, only *assists* extraction, hypothesis
  generation, interpretation and explanation; it never overrides the
  deterministic scoring or decision logic. Its output is treated as untrusted and
  validated — supporting quotes must appear verbatim in the source documents and
  citations must reference real evidence, or the suggestion is dropped.

---

## 8. Demonstrating honestly

NeuroSync is built so its reasoning can be audited:

- Every conflict states **why** it was flagged.
- Every agent action stores its **reason** and the **blackboard changes** it made.
- The scheduler records its **priority breakdown** for each decision.
- Conclusions list their **supporting evidence**, **unresolved questions** and
  **limitations**.
- All demonstration data is **explicitly labelled** and can be removed without
  affecting your own uploads.
