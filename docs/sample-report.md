<!-- Sample report generated from the built-in demonstration scenario -->
<!-- Machine M-17 Temperature Disagreement Investigation -->

# Investigation Report: Machine M-17 Temperature Disagreement Investigation

*Generated: 2026-10-10T22:14:24.336017+00:00*

## Investigation Title and Identifier
Machine M-17 Temperature Disagreement Investigation (id 1).


## Investigation Title
Machine M-17 Temperature Disagreement Investigation


## Objective
Two inspection reports record different temperatures for machine M-17 at the same time (92°C vs 76°C). Can the disagreement be explained, and does the later sensor recalibration account for it?


## Documents Analyzed
3 document(s) were analyzed. These are demonstration documents.

- [Inspection_Report_A.txt](/documents/1) (txt, 115 bytes, 1 claim(s), status=processed)
- [Inspection_Report_B.txt](/documents/2) (txt, 115 bytes, 1 claim(s), status=processed)
- [Maintenance_Log_C.txt](/documents/3) (txt, 91 bytes, 1 claim(s), status=processed)

## Claims Extracted
3 claim(s) were extracted and are treated as reported observations, not established facts.

- [Inspection_Report_A.txt](/documents/1) claim 1: &quot;[DEMONSTRATION DATA] Inspection Report A Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM.&quot; (numeric=92.0 °C) [source: Inspection_Report_A.txt]
- [Inspection_Report_B.txt](/documents/2) claim 2: &quot;[DEMONSTRATION DATA] Inspection Report B Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM.&quot; (numeric=76.0 °C) [source: Inspection_Report_B.txt]
- [Maintenance_Log_C.txt](/documents/3) claim 3: &quot;[DEMONSTRATION DATA] Maintenance Log C The temperature sensor was recalibrated at 10:30 AM.&quot; [source: Maintenance_Log_C.txt]

## Key Observations
- Inspection_Report_A.txt: [DEMONSTRATION DATA] Inspection Report A Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM. (source: Inspection_Report_A.txt)
- Inspection_Report_B.txt: [DEMONSTRATION DATA] Inspection Report B Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM. (source: Inspection_Report_B.txt)
- Maintenance_Log_C.txt: [DEMONSTRATION DATA] Maintenance Log C The temperature sensor was recalibrated at 10:30 AM. (source: Maintenance_Log_C.txt)

## Conflicting Claims
1 potential conflict(s) were identified.

- Conflict 1: &#x27;temperature&#x27; is reported as 92°C and 76°C within the same time period with no distinguishing context (17% difference).

## Conflict Classifications
- Conflict 1: type=numerical_disagreement, severity=medium, status=human_review, claims 1 vs 2

## Evidence Supporting Each Relevant Claim
Evidence explicitly recorded against each claim that takes part in a conflict.

- Claim 1: evidence 1 [measurement] Claim A states: &quot;[DEMONSTRATION DATA] Inspection Report A Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM.&quot; (source: Inspection_Report_A.txt)
- Claim 2: evidence 2 [measurement] Claim B states: &quot;[DEMONSTRATION DATA] Inspection Report B Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM.&quot; (source: Inspection_Report_B.txt)

## Evidence Contradicting Each Relevant Claim
Evidence recorded against the opposing claim in each recorded conflict. No contradiction is inferred beyond what the conflict identifies.

- Claim 1: evidence 2 [measurement] Claim B states: &quot;[DEMONSTRATION DATA] Inspection Report B Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM.&quot; (Recorded conflict 1 places this claim against claim 2.) (source: Inspection_Report_B.txt)
- Claim 2: evidence 1 [measurement] Claim A states: &quot;[DEMONSTRATION DATA] Inspection Report A Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM.&quot; (Recorded conflict 1 places this claim against claim 1.) (source: Inspection_Report_A.txt)

## Competing Hypotheses
4 explanation(s) were proposed. These are inferred explanations, not observed facts.

- Conflict 1: &quot;Sensor or measurement-source issue&quot; (status=review_required, support=0.72, origin=inferred)
- Conflict 1: &quot;Measurement or transcription error&quot; (status=inconclusive, support=0.50, origin=inferred)
- Conflict 1: &quot;Genuine difference under otherwise similar conditions&quot; (status=inconclusive, support=0.40, origin=inferred)
- Conflict 1: &quot;Incomplete reporting / missing context&quot; (status=inconclusive, support=0.50, origin=inferred)

## Hypothesis Ranking
Competing hypotheses are ranked by documented evidence weight. Scores are bounded support indicators, not calibrated probabilities.

- Conflict 1 rank 1: &quot;Sensor or measurement-source issue&quot; (support=0.72, confidence=0.68, +weight=0.81, -weight=0.00, distinct sources=1, direct evidence=True, margin to next=0.22)
- Conflict 1 rank 2: &quot;Measurement or transcription error&quot; (support=0.50, confidence=0.40, +weight=0.00, -weight=0.00, distinct sources=0, direct evidence=False, margin to next=0.00)
- Conflict 1 rank 3: &quot;Incomplete reporting / missing context&quot; (support=0.50, confidence=0.40, +weight=0.00, -weight=0.00, distinct sources=0, direct evidence=False, margin to next=0.10)
- Conflict 1 rank 4: &quot;Genuine difference under otherwise similar conditions&quot; (support=0.40, confidence=0.32, +weight=0.00, -weight=0.32, distinct sources=0, direct evidence=False)

## Evidence Supporting Each Hypothesis
- Evidence 3 supports hypothesis 1: Document &#x27;Maintenance_Log_C.txt&#x27; contains a calibration record: &quot;[DEMONSTRATION DATA] Maintenance Log C The temperature sensor was recalibrated at 10:30 AM.&quot;

## Evidence Contradicting Each Hypothesis
- Evidence 4 contradicts hypothesis 3: No operating-condition data was found in the available documents for this conflict.

## Verification Results
Reliability/relevance are bounded quality indicators; &#x27;unverified&#x27; means no verification step has been recorded.

- Evidence 1 [measurement] verification=verified (reliability=0.70, relevance=0.60, weight=0.70)
- Evidence 2 [measurement] verification=verified (reliability=0.70, relevance=0.60, weight=0.70)
- Evidence 3 [calibration_record] verification=verified (reliability=0.80, relevance=0.80, weight=0.81)
- Evidence 4 [missing] verification=unsupported (reliability=0.20, relevance=0.50, weight=0.32)

## Final Conclusion or Inconclusive Status
Each conclusion is the system&#x27;s adjudication for a recorded conflict. No definitive conclusion was produced; the investigation is inconclusive.

- Conflict 1 -&gt; human_review_required (confidence 0.43): The evidence about &#x27;numerical_disagreement&#x27; could not be resolved automatically from the available documents. Human review is recommended. Best-supported explanation: &quot;Sensor or measurement-source issue&quot; (support 0.72). The two readings may come from different measurement sources, or the sensor may have been miscalibrated or drifting, so the disagreement reflects instrumentation rather than a real change in the machine. Supporting evidence: Evidence 3 (calibration_record from Maintenance_Log_C.txt): Document &#x27;Maintenance_Log_C.txt&#x27; contains a calibration record: &quot;[DEMONSTRATION DATA] Maintenance Log C The temperature sensor was recalibrated at 10:30 AM.&quot;.

## Confidence and its Limitations
Overall confidence (mean of conclusions): 0.43. Confidence is the mean of the per-conflict conclusion support scores. It is a bounded support indicator derived from documented evidence weights, NOT a statistically calibrated probability. A higher value means more (reliable, direct, source-diverse) supporting evidence relative to contradicting evidence; it does not mean &#x27;X% likely to be true&#x27;.

- Confidence scores are bounded support indicators, not calibrated probabilities.
- Only information present in the uploaded documents was considered.

## Unresolved Questions
- Calibration history of the sensor and the measurement source for each reading.
- Assumption: A sensor or instrument was used and may not be fully trustworthy.
- Independent confirmation of either value.
- Assumption: Only one of the values is correct.
- Timing, location and conditions of each measurement.
- Assumption: The reports omit relevant details.
- Conditions and exact timing for each measurement.
- Assumption: Conditions were comparable.

## Evidence Gaps and Uncertainty
Missing evidence that limits confidence in any conclusion.

- Conflict 1: No operating-condition data was found in the available documents for this conflict.
- Conflict 1: Calibration history of the sensor and the measurement source for each reading.
- Conflict 1: Independent confirmation of either value.
- Conflict 1: Conditions and exact timing for each measurement.
- Conflict 1: Timing, location and conditions of each measurement.

## Human Review Status
Status: awaiting review (0 decision(s) recorded).

- Conflict 1 is awaiting human review.

## Recommended Next Steps
- Route conflict 1 to a human reviewer with the attached evidence.

## Human Review Notes
This report was produced by an automated evidence-driven system. It supports, but does not replace, professional judgement.

- Conflict 1 requires human review.

## Human Review Decisions
Recorded human decisions on this investigation&#x27;s conclusions.

- No human review decisions have been recorded yet.

## Agent Activity Summary
7 agent action(s) were recorded.

- Evidence Collector: 1 action(s), 1 success, 0 failed, 12 ms total
- Conflict Detector: 2 action(s), 1 success, 0 failed, 5 ms total
- Hypothesis Generator: 1 action(s), 1 success, 0 failed, 10 ms total
- Investigator: 1 action(s), 1 success, 0 failed, 6 ms total
- Verification Agent: 1 action(s), 1 success, 0 failed, 7 ms total
- Decision Agent: 1 action(s), 1 success, 0 failed, 4 ms total

## Limitations and Timestamps
All times are UTC. Confidence is a bounded support indicator, not a probability.

- Created: 2026-10-10T22:14:24.030732+00:00
- Started: 2026-10-10T22:14:24.035023+00:00
- Completed: 2026-10-10T22:14:24.313814+00:00
- Report generated: 2026-10-10T22:14:24.335851+00:00
- Duration: 0.3 second(s)
- Limitation: Confidence scores are bounded support indicators, not calibrated probabilities.
- Limitation: Only information present in the uploaded documents was considered.

## Investigation Stopping Reason
Stopped because no eligible agent could provide further useful information.


## Audit Trail
Every recorded blackboard change for this investigation, newest last.

- #1 2026-10-10T22:14:24.057810+00:00 [claim None] extracted by agent: Extracted 1 rule-based and 0 LLM-suggested claim(s) and 1 observation(s) from &#x27;Inspection_Report_A.txt&#x27;.
- #2 2026-10-10T22:14:24.060315+00:00 [claim None] extracted by agent: Extracted 1 rule-based and 0 LLM-suggested claim(s) and 1 observation(s) from &#x27;Inspection_Report_B.txt&#x27;.
- #3 2026-10-10T22:14:24.061884+00:00 [claim None] extracted by agent: Extracted 1 rule-based and 0 LLM-suggested claim(s) and 1 observation(s) from &#x27;Maintenance_Log_C.txt&#x27;.
- #4 2026-10-10T22:14:24.124905+00:00 [conflict 1] created by agent: Detected numerical_disagreement (severity=medium): &#x27;temperature&#x27; is reported as 92°C and 76°C within the same time period with no distinguishing context (17% difference).
- #5 2026-10-10T22:14:24.160308+00:00 [evidence 1] created by agent: [measurement] Claim A states: &quot;[DEMONSTRATION DATA] Inspection Report A Machine M-17 reached a temperature of 92°C during inspection at 10:00 AM.&quot;
- #6 2026-10-10T22:14:24.161410+00:00 [evidence 2] created by agent: [measurement] Claim B states: &quot;[DEMONSTRATION DATA] Inspection Report B Machine M-17 reached a temperature of 76°C during inspection at 10:00 AM.&quot;
- #7 2026-10-10T22:14:24.162370+00:00 [hypothesis 1] created by agent: Proposed hypothesis &#x27;Sensor or measurement-source issue&#x27; for conflict 1.
- #8 2026-10-10T22:14:24.162795+00:00 [hypothesis 2] created by agent: Proposed hypothesis &#x27;Measurement or transcription error&#x27; for conflict 1.
- #9 2026-10-10T22:14:24.163166+00:00 [hypothesis 3] created by agent: Proposed hypothesis &#x27;Genuine difference under otherwise similar conditions&#x27; for conflict 1.
- #10 2026-10-10T22:14:24.163491+00:00 [hypothesis 4] created by agent: Proposed hypothesis &#x27;Incomplete reporting / missing context&#x27; for conflict 1.
- #11 2026-10-10T22:14:24.204703+00:00 [evidence 3] created by agent: [calibration_record] Document &#x27;Maintenance_Log_C.txt&#x27; contains a calibration record: &quot;[DEMONSTRATION DATA] Maintenance Log C The temperature sensor was recalibrated at 10:30 AM.&quot;
- #12 2026-10-10T22:14:24.205981+00:00 [evidence 4] created by agent: [missing] No operating-condition data was found in the available documents for this conflict.
- #13 2026-10-10T22:14:24.230676+00:00 [hypothesis 1] verified by agent: Hypothesis &#x27;Sensor or measurement-source issue&#x27; evaluated as review_required (support=0.72, confidence=0.68).
- #14 2026-10-10T22:14:24.231752+00:00 [hypothesis 2] verified by agent: Hypothesis &#x27;Measurement or transcription error&#x27; evaluated as inconclusive (support=0.50, confidence=0.40).
- #15 2026-10-10T22:14:24.233050+00:00 [hypothesis 3] verified by agent: Hypothesis &#x27;Genuine difference under otherwise similar conditions&#x27; evaluated as inconclusive (support=0.40, confidence=0.32).
- #16 2026-10-10T22:14:24.233854+00:00 [hypothesis 4] verified by agent: Hypothesis &#x27;Incomplete reporting / missing context&#x27; evaluated as inconclusive (support=0.50, confidence=0.40).
- #17 2026-10-10T22:14:24.234594+00:00 [evidence None] verification_completed by agent: Verified 4 evidence item(s) for conflict 1.
- #18 2026-10-10T22:14:24.274164+00:00 [conclusion 1] created by agent: Conclusion for conflict 1: human_review_required (confidence 0.43).

## Report Warnings
Data-completeness notices that affect how this report should be read.

- At least one conclusion is inconclusive or requires human review; the report does not assert a definitive finding.
- A conflict is awaiting human review; no decision has been recorded yet.
