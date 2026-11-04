// Shared API types mirroring the FastAPI Pydantic schemas.

export type Severity = "critical" | "high" | "medium" | "low";
export type ConflictStatus =
  | "open"
  | "investigating"
  | "resolved"
  | "inconclusive"
  | "human_review";
export type HypothesisStatus =
  | "proposed"
  | "supported"
  | "contradicted"
  | "inconclusive"
  | "review_required"
  | "human_reviewed";
export type InvestigationStatus =
  | "created"
  | "running"
  | "paused"
  | "completed"
  | "cancelled"
  | "error";
export type AgentStatus =
  | "idle"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "waiting_for_evidence"
  | "awaiting_human_review";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DocumentOut {
  id: number;
  filename: string;
  file_type: string;
  content_type: string;
  file_size: number;
  status: string;
  error_message: string;
  is_demo: boolean;
  uploaded_at: string | null;
  processed_at: string | null;
  claim_count: number;
  conflict_count: number;
  observation_count: number;
  source_metadata: Record<string, unknown>;
}

export interface DocumentDetail extends DocumentOut {
  text_preview: string;
  char_count: number;
}

export interface DocumentUploadResponse {
  id: number;
  filename: string;
  status: string;
  message: string;
  claim_count: number;
  conflict_count: number;
  duplicate: boolean;
}

export interface ClaimOut {
  id: number;
  document_id: number;
  observation_id: number | null;
  claim_text: string;
  subject: string;
  predicate: string;
  object_value: string;
  numeric_value: number | null;
  unit: string;
  polarity: string;
  claim_type: string;
  timestamp_value: string | null;
  source_reference: string;
  source_location: string;
  confidence: number;
  created_at: string | null;
  document_filename: string | null;
}

export interface ConflictOut {
  id: number;
  claim_a_id: number;
  claim_b_id: number;
  conflict_type: string;
  description: string;
  severity: Severity;
  detection_method: string;
  confidence: number;
  status: ConflictStatus;
  resolution_summary: string;
  created_at: string | null;
  updated_at: string | null;
  document_a: string | null;
  document_b: string | null;
  evidence_count: number;
  hypothesis_count: number;
}

export interface ConclusionData {
  id: number;
  decision_type: string;
  conclusion: string;
  confidence: number;
  supporting_evidence_ids: number[];
  unresolved_questions: string[];
  limitations: string[];
}

export type ReviewDecision =
  | "approved"
  | "rejected"
  | "inconclusive"
  | "request_more_investigation"
  | "reopen";

export interface HumanReviewOut {
  id: number;
  conclusion_id: number | null;
  conflict_id: number | null;
  investigation_id: number | null;
  decision: ReviewDecision;
  reviewer: string;
  note: string;
  previous_decision_type: string;
  created_at: string | null;
}

export interface ReviewResultOut {
  review: HumanReviewOut;
  conflict_status: string;
  conclusion_decision_type: string;
  message: string;
}

export interface RankingEvidence {
  id: number;
  evidence_type: string;
  origin: string;
  description: string;
  source_reference: string;
  document_filename: string | null;
  verification_status: string;
  weight: number;
}

export interface RankingCriteria {
  supporting_evidence_weight: number;
  contradicting_evidence_weight: number;
  distinct_supporting_sources: number;
  has_direct_supporting_evidence: boolean;
  supporting_evidence_count: number;
  contradicting_evidence_count: number;
}

export interface HypothesisRanking {
  hypothesis_id: number;
  conflict_id: number;
  rank: number;
  title: string;
  explanation: string;
  status: HypothesisStatus;
  support_score: number;
  confidence: number;
  confidence_caveat: string;
  criteria: RankingCriteria;
  assumptions: string[];
  missing_information: string[];
  supporting_evidence: RankingEvidence[];
  contradicting_evidence: RankingEvidence[];
  ranking_explanation: string;
  margin_to_next: number | null;
}

export interface AuditEventOut {
  id: number;
  investigation_id: number | null;
  conflict_id: number | null;
  entity_type: string;
  entity_id: number | null;
  action: string;
  actor: string;
  summary: string;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface ConflictDetail extends ConflictOut {
  claim_a: ClaimOut | null;
  claim_b: ClaimOut | null;
  evidence: EvidenceOut[];
  hypotheses: HypothesisOut[];
  investigations: {
    id: number;
    name: string;
    status: string;
    iteration_count: number;
    stop_reason: string;
  }[];
  conclusion: ConclusionData | null;
  why_flagged: string;
}

export interface EvidenceOut {
  id: number;
  conflict_id: number;
  claim_id: number | null;
  document_id: number | null;
  evidence_type: string;
  origin: string;
  description: string;
  source_reference: string;
  source_location: string;
  supports_hypothesis_id: number | null;
  contradicts_hypothesis_id: number | null;
  relevance_score: number;
  reliability_score: number;
  directness: number;
  verification_status: string;
  created_at: string | null;
  document_filename: string | null;
  assessment: EvidenceAssessment | null;
}

export interface EvidenceFactor {
  value: number;
  label: string;
  explanation: string;
}

export interface EvidenceAssessment {
  factors: {
    relevance: EvidenceFactor;
    provenance: EvidenceFactor;
    recency: EvidenceFactor;
    completeness: EvidenceFactor;
    corroboration: EvidenceFactor;
    contradictory_evidence: EvidenceFactor;
  };
  source_reliability: {
    label: string;
    heuristic_indicator: number;
    note: string;
  };
  overall_score: number;
  overall_label: string;
  missing_information: string[];
  formula: string;
  caveat: string;
}

export interface HypothesisOut {
  id: number;
  conflict_id: number;
  title: string;
  explanation: string;
  supporting_evidence_ids: number[];
  contradicting_evidence_ids: number[];
  assumptions: string[];
  missing_information: string[];
  confidence: number;
  support_score: number;
  status: HypothesisStatus;
  origin: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface InvestigationOut {
  id: number;
  name: string;
  research_question: string;
  status: InvestigationStatus;
  iteration_limit: number;
  min_evidence_threshold: number;
  enable_llm: boolean;
  iteration_count: number;
  current_objective: string;
  current_agent: string;
  current_priority: number;
  current_info_gain: number;
  stop_reason: string;
  is_demo: boolean;
  error_message: string;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
  document_count: number;
  conflict_count: number;
  open_conflict_count: number;
  evidence_count: number;
  conclusion_count: number;
}

export interface ActivityOut {
  id: number;
  investigation_id: number | null;
  conflict_id: number | null;
  agent_name: string;
  action: string;
  input_summary: string;
  output_summary: string;
  reason: string;
  blackboard_changes: Record<string, unknown>;
  status: string;
  duration_ms: number;
  sequence: number;
  attempt: number;
  input_record_ids: number[];
  output_record_ids: number[];
  error: string;
  state_summary: string;
  created_at: string | null;
}

export interface AgentStatusOut {
  name: string;
  responsibility: string;
  status: AgentStatus;
  last_action: string;
  tasks_completed: number;
  last_duration_ms: number;
  recent_result: string;
  required_inputs: string[];
  expected_outputs: string[];
  run_conditions: string[];
  stop_conditions: string[];
}

export interface ReportSection {
  heading: string;
  body: string;
  items: string[];
}

export interface ReportOut {
  investigation_id: number;
  title: string;
  objective: string;
  generated_at: string;
  sections: ReportSection[];
  markdown: string;
  json_data: ReportData;
  stopping_reason: string;
  confidence: number;
  confidence_explanation: string;
  warnings: string[];
  schema_version: number;
}

export type ReportKind = "observed" | "inferred";

export interface ReportDocument {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  is_demo: boolean;
  uploaded_at: string | null;
  processed_at: string | null;
  claim_count: number;
  link: string;
  kind: ReportKind;
}

export interface ReportClaim {
  id: number;
  document_id: number;
  document_filename: string | null;
  document_link: string | null;
  claim_text: string;
  subject: string;
  predicate: string;
  object_value: string;
  numeric_value: number | null;
  unit: string;
  polarity: string;
  claim_type: string;
  source_reference: string;
  source_location: string;
  timestamp_value: string | null;
  confidence: number;
  created_at: string | null;
  kind: ReportKind;
}

export interface ReportClaimRef {
  id: number;
  text: string;
  document_id: number | null;
  document_filename: string | null;
  document_link: string | null;
}

export interface ReportConflict {
  id: number;
  type: string;
  severity: string;
  status: string;
  description: string;
  detection_method: string;
  confidence: number;
  created_at: string | null;
  claim_a: ReportClaimRef | null;
  claim_b: ReportClaimRef | null;
  link: string;
  kind: ReportKind;
}

export interface ReportEvidenceRef {
  id: number;
  description: string;
  evidence_type: string;
  source_reference: string;
  document_id: number | null;
  document_link: string | null;
  document_filename: string | null;
}

export interface ReportEvidenceByClaim {
  claim_id: number;
  claim_text: string | null;
  document_id: number | null;
  document_link: string | null;
  conflict_id: number;
  conflict_link: string;
  supporting_evidence: ReportEvidenceRef[];
  contradicting_evidence: ReportEvidenceRef[];
  basis: string;
}

export interface ReportEvidence {
  id: number;
  conflict_id: number;
  conflict_link: string;
  claim_id: number | null;
  document_id: number | null;
  document_filename: string | null;
  document_link: string | null;
  evidence_type: string;
  origin: string;
  kind: ReportKind;
  description: string;
  source_reference: string;
  source_location: string;
  supports_hypothesis_id: number | null;
  contradicts_hypothesis_id: number | null;
  relevance_score: number;
  reliability_score: number;
  directness: number;
  weight: number;
  verification_status: string;
  created_at: string | null;
}

export interface ReportEvidenceRefLite {
  id: number | null;
  exists: boolean;
  description: string;
  evidence_type: string | null;
  document_link: string | null;
}

export interface ReportHypothesis {
  id: number;
  conflict_id: number;
  conflict_link: string;
  title: string;
  explanation: string;
  status: string;
  origin: string;
  kind: ReportKind;
  support_score: number;
  confidence: number;
  assumptions: string[];
  missing_information: string[];
  supporting_evidence: ReportEvidenceRefLite[];
  contradicting_evidence: ReportEvidenceRefLite[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ReportVerification {
  evidence_id: number;
  evidence_type: string;
  description: string;
  verification_status: string;
  reliability_score: number;
  relevance_score: number;
  directness: number;
  weight: number;
  document_link: string | null;
  document_filename: string | null;
}

export interface ReportConclusion {
  id: number;
  conflict_id: number | null;
  conflict_link: string | null;
  decision_type: string;
  conclusion: string;
  confidence: number;
  supporting_evidence_ids: number[];
  supporting_evidence: ReportEvidenceRefLite[];
  unresolved_questions: string[];
  limitations: string[];
  is_inconclusive: boolean;
  created_at: string | null;
  superseded_by_id: number | null;
}

export interface ReportReview {
  id: number;
  conclusion_id: number | null;
  conflict_id: number | null;
  decision: string;
  reviewer: string;
  note: string;
  previous_decision_type: string;
  created_at: string | null;
}

export interface ReportActivityBucket {
  agent_name: string;
  actions: number;
  successes: number;
  failures: number;
  total_duration_ms: number;
}

export interface ReportActivityItem {
  id: number;
  sequence: number;
  attempt: number;
  agent_name: string;
  action: string;
  input_summary: string;
  output_summary: string;
  reason: string;
  status: string;
  duration_ms: number;
  error: string;
  created_at: string | null;
}

export interface ReportAuditItem {
  id: number;
  entity_type: string;
  entity_id: number | null;
  action: string;
  actor: string;
  summary: string;
  created_at: string | null;
}

export interface ReportData {
  schema_version: number;
  generated_at: string;
  generator: string;
  investigation: {
    id: number;
    title: string;
    question: string;
    status: string;
    stop_reason: string;
    stop_reason_text: string;
    iteration_count: number;
    iteration_limit: number;
    is_demo: boolean;
    link: string;
  };
  documents: ReportDocument[];
  claims: ReportClaim[];
  conflicts: ReportConflict[];
  evidence: ReportEvidence[];
  evidence_by_claim: ReportEvidenceByClaim[];
  hypotheses: ReportHypothesis[];
  verification: ReportVerification[];
  conclusions: ReportConclusion[];
  confidence: { value: number; basis: string; interpretation: string };
  human_reviews: ReportReview[];
  human_review_status: {
    required: boolean;
    conflicts_awaiting_review: number[];
    decisions_recorded: number;
    status: string;
  };
  agent_activity: {
    count: number;
    by_agent: ReportActivityBucket[];
    timeline: ReportActivityItem[];
  };
  audit_trail: ReportAuditItem[];
  evidence_gaps: string[];
  unresolved_questions: string[];
  limitations: string[];
  recommendations: string[];
  timestamps: Record<string, string | number | null>;
  warnings: string[];
}

export interface BlackboardCounts {
  documents: number;
  observations: number;
  claims: number;
  conflicts: number;
  unresolved_conflicts: number;
  evidence: number;
  hypotheses: number;
  investigations: number;
  active_investigations: number;
  conclusions: number;
  human_review_requests: number;
  human_reviews: number;
  audit_events: number;
  pending_verification: number;
  evidence_gaps: number;
}

export interface GraphNode {
  id: string;
  node_type: string;
  label: string;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  label: string;
}

export interface BlackboardGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface BlackboardSnapshot {
  generated_at: string;
  counts: BlackboardCounts;
  graph: BlackboardGraph;
  recent_activity: {
    id: number;
    agent: string;
    action: string;
    output_summary: string;
    status: string;
    created_at: string;
  }[];
  severity_distribution: { severity: string; count: number }[];
  activity_timeline: { date: string; count: number }[];
  conflict_type_distribution: { value: string; count: number }[];
  conflict_status_distribution: { value: string; count: number }[];
  investigation_status_distribution: { value: string; count: number }[];
  evidence_verification_distribution: { value: string; count: number }[];
  recent_events: BlackboardEventOut[];
  relation_counts: Record<string, number>;
}

export interface BlackboardEventOut {
  id: number;
  investigation_id: number | null;
  event_type: string;
  agent_name: string | null;
  entity_type: string | null;
  entity_id: number | null;
  related: { type: string; id: number }[];
  payload: Record<string, unknown>;
  created_at: string;
  processed: boolean;
}

export interface BlackboardRelationOut {
  id: number;
  investigation_id: number | null;
  source_type: string;
  source_id: number;
  target_type: string;
  target_id: number;
  relation_type: string;
  agent_name: string;
  reason: string;
  created_at: string | null;
}

export interface ConnectedRecordOut {
  relation_id: number;
  relation_type: string;
  direction: "incoming" | "outgoing";
  label: string;
  other: { type: string; id: number };
  agent_name: string;
  reason: string;
}

export interface TraceResponse {
  record: { type: string; id: number; exists: boolean; label: string };
  relations: ConnectedRecordOut[];
  events: Record<string, unknown>[];
  audit: Record<string, unknown>[];
  influenced_by: { type: string; id: number; via: string; direction: string }[];
  why: string[];
}

export interface ReevaluationSummary {
  tasks: number;
  genuine: number;
  reopened: number;
  hypotheses_rescored: number;
  conclusions_revised: number;
  skipped: number;
}

export interface HealthInfo {
  status: string;
  app: string;
  version: string;
  ai_configured: boolean;
  mode: string;
  llm_model: string | null;
  reasoning_mode?: "deterministic" | "ai_assisted";
  effective_mode?: "deterministic" | "ai_assisted";
}

export interface ReasoningSettings {
  reasoning_mode: "deterministic" | "ai_assisted";
  effective_mode: "deterministic" | "ai_assisted";
  llm_configured: boolean;
  model: string | null;
  provider: string | null;
  available_modes: ("deterministic" | "ai_assisted")[];
  note: string;
}

export interface InvestigationEvent {
  id: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  investigation_id?: number | null;
  agent_name?: string | null;
  entity_type?: string | null;
  entity_id?: number | null;
  related?: { type: string; id: number }[];
}

export interface InvestigationProgress {
  investigation_id: number;
  status: string;
  current_agent: string;
  current_objective: string;
  iteration_count: number;
  iteration_limit: number;
  stop_reason: string;
  updated_at: string | null;
  executions: number;
  completed: number;
  failed: number;
  skipped: number;
  conflicts_total: number;
  conflicts_open: number;
}

export interface DemoLoadResponse {
  ok: boolean;
  message: string;
  is_demo: boolean;
  documents: { id: number; filename: string }[];
  investigation_id: number;
}

export interface KGNode {
  id: string;
  node_type: string;
  label: string;
  data: Record<string, unknown>;
}

export interface KGEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  label: string;
  verified: boolean;
  agent_name: string;
  reason: string;
}

export interface KnowledgeGraph {
  nodes: KGNode[];
  edges: KGEdge[];
  node_type_counts: Record<string, number>;
  relation_type_counts: Record<string, number>;
  available_node_types: string[];
  required_relation_types: string[];
  available_relation_types: string[];
  totals: { nodes: number; edges: number };
  truncated: boolean;
  investigation_id: number | null;
}

// --------------------------------------------------------- Fact verification
export type FactVerdict =
  | "supported"
  | "contradicted"
  | "partially_supported"
  | "unverified";

export interface VerificationSource {
  document_id: number | null;
  document_filename: string | null;
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  text_location: string;
  snippet: string;
  link: string | null;
}

export interface VerificationEvidenceItem {
  kind: string;
  record_id: number | null;
  relation: string;
  reason: string;
  text: string;
  independence: string;
  source: VerificationSource;
  timestamp_value: string | null;
}

export interface FactVerificationOut {
  claim_id: number | null;
  claim_text: string;
  subject: string;
  predicate: string;
  object_value: string;
  numeric_value: number | null;
  unit: string;
  polarity: string;
  claim_type: string;
  timestamp_value: string | null;
  claim_confidence: number;
  document_id: number | null;
  document_filename: string | null;
  source: VerificationSource;
  verdict: FactVerdict;
  verdict_label: string;
  confidence: number;
  summary: string;
  explanation: string;
  supporting_evidence: VerificationEvidenceItem[];
  contradicting_evidence: VerificationEvidenceItem[];
  neutral_evidence: VerificationEvidenceItem[];
  missing_information: string[];
  documents_considered: number;
  claims_compared: number;
  stored_evidence_considered: number;
  method: string;
  methodology: string;
  caveat: string;
  analysis_notes: string[];
  analyzed_at: string | null;
}

export interface VerdictBreakdown {
  supported: number;
  contradicted: number;
  partially_supported: number;
  unverified: number;
}

export interface FactVerificationList {
  items: FactVerificationOut[];
  total: number;
  page: number;
  page_size: number;
  counts: VerdictBreakdown;
  documents_considered: number;
  investigation_id: number | null;
  investigation_name: string | null;
  methodology: string;
  caveat: string;
}

export interface FactVerificationSummary {
  total_claims: number;
  counts: VerdictBreakdown;
  documents_considered: number;
  claims_with_contradictions: number;
  claims_missing_context: number;
  methodology: string;
  caveat: string;
}

// ---------------------------------------------------------- Source credibility
export type CredibilityLevel =
  | "well_documented"
  | "partially_documented"
  | "limited_documentation"
  | "unverifiable";

export type CredibilityFactorStatus =
  | "recorded"
  | "partial"
  | "unknown"
  | "not_applicable"
  | "inconsistent"
  | "mixed"
  | "consistent";

export interface CredibilityFactor {
  key: string;
  label: string;
  status: CredibilityFactorStatus | string;
  // null means the factor could not be assessed from stored information. It is
  // excluded from the aggregate and must never be rendered as a zero.
  score: number | null;
  summary: string;
  explanation: string;
  inputs: string[];
  missing: string[];
}

export interface CredibilityEvidence {
  relation: string;
  claim_id: number | null;
  claim_text: string;
  other_document_id: number | null;
  other_document_filename: string | null;
  text: string;
  reason: string;
  independence: string;
}

export interface CredibilityConsistency {
  status: string;
  score: number | null;
  claims_checked: number;
  supported: number;
  contradicted: number;
  partially_supported: number;
  unverified: number;
  explanation: string;
  supporting: CredibilityEvidence[];
  contradicting: CredibilityEvidence[];
}

export interface SourceMetadataOut {
  author: string | null;
  organization: string | null;
  publication_date: string | null;
  publication_date_raw: string | null;
  publication_date_precision: string | null;
  source_type: string | null;
  identifiers: string[];
  version: string | null;
  signature: string | null;
  fields: Record<string, string>;
  raw: Record<string, unknown>;
}

export interface SourceCredibilityOut {
  document_id: number;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  is_demo: boolean;
  uploaded_at: string | null;
  processed_at: string | null;
  checksum: string;
  stored_file_present: boolean;
  stored_file_size: number | null;
  content_available: boolean;
  char_count: number;
  claim_count: number;
  observation_count: number;
  evidence_count: number;
  source_metadata: SourceMetadataOut;
  overall_label: CredibilityLevel;
  overall_label_display: string;
  overall_score: number | null;
  coverage: number;
  summary: string;
  explanation: string;
  factors: Record<string, CredibilityFactor>;
  unknown_factors: string[];
  warnings: string[];
  missing_information: string[];
  consistency: CredibilityConsistency;
  methodology: string;
  caveat: string;
  analyzed_at: string | null;
}

export interface CredibilityCounts {
  well_documented: number;
  partially_documented: number;
  limited_documentation: number;
  unverifiable: number;
  unknown_author: number;
  unknown_organization: number;
  unknown_publication_date: number;
  with_consistency_conflicts: number;
  demonstration_sources: number;
}

export interface SourceCredibilityList {
  items: SourceCredibilityOut[];
  total: number;
  page: number;
  page_size: number;
  counts: CredibilityCounts;
  documents_considered: number;
  investigation_id: number | null;
  investigation_name: string | null;
  methodology: string;
  caveat: string;
}

// ------------------------------------------------------- Investigation chat
export interface ChatCitation {
  number: number;
  kind: string;
  record_id: number | null;
  label: string;
  document_id: number | null;
  document_filename: string | null;
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  text_location: string;
  snippet: string;
  link: string | null;
}

export interface ChatAnswer {
  investigation_id: number;
  investigation_name: string;
  question: string;
  intent: string;
  answer: string;
  insufficient_information: boolean;
  missing_information: string[];
  citations: ChatCitation[];
  follow_up_questions: string[];
  data_sources: Record<string, number>;
  methodology: string;
  caveat: string;
  analyzed_at: string;
}

export interface ChatSuggestions {
  investigation_id: number;
  investigation_name: string;
  suggestions: string[];
  note: string;
}

// -------------------------------------------------- Evaluation dashboard
export type EvaluationKind = "conflict_detection" | "evidence_verification";
export type EvaluationProvenance = "reference_labelled" | "user_labelled";

export interface EvaluationCaseResultOut {
  id: number;
  case_key: string;
  category: string;
  expected: Record<string, any>;
  predicted: Record<string, any>;
  passed: boolean;
  duration_ms: number;
  explanation: string;
}

export interface EvaluationRunSummaryOut {
  id: number;
  dataset_id: number;
  dataset_name: string;
  kind: string;
  provenance: string;
  status: string;
  case_count: number;
  passed: number;
  failed: number;
  duration_ms: number;
  error: string;
  metrics: Record<string, any>;
  confusion: Record<string, any>;
  started_at: string | null;
  completed_at: string | null;
}

export interface EvaluationRunOut extends EvaluationRunSummaryOut {
  by_category: Record<string, any>;
  failures: Record<string, any>[];
  config: Record<string, any>;
  results: EvaluationCaseResultOut[];
}

export interface EvaluationDatasetOut {
  id: number;
  key: string;
  name: string;
  description: string;
  kind: string;
  source: string;
  version: string;
  is_builtin: boolean;
  case_count: number;
  created_at: string | null;
  updated_at: string | null;
  latest_run: EvaluationRunSummaryOut | null;
}

export interface EvaluationCaseOut {
  id: number;
  case_key: string;
  category: string;
  payload: Record<string, any>;
  expected: Record<string, any>;
  rationale: string;
  created_at: string | null;
}

export interface EvaluationDatasetDetailOut extends EvaluationDatasetOut {
  cases: EvaluationCaseOut[];
}

export interface AgentPerformanceOut {
  name: string;
  responsibility: string;
  status: string;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  skipped_tasks: number;
  total_duration_ms: number;
  avg_duration_ms: number | null;
  max_duration_ms: number;
  last_action: string;
  last_activity_at: string | null;
}

export interface AgentPerformanceSummary {
  agents: AgentPerformanceOut[];
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  skipped_tasks: number;
  avg_duration_ms: number | null;
}

export interface DocumentAnalyticsOut {
  documents_total: number;
  documents_processed: number;
  documents_pending: number;
  documents_processing: number;
  documents_error: number;
  documents_by_status: Record<string, number>;
  documents_with_timing: number;
  avg_processing_ms: number | null;
  max_processing_ms: number | null;
  total_processing_ms: number;
  claims_extracted: number;
  documents_with_claims: number;
  conflicts_detected: number;
  conflicts_resolved: number;
  hypotheses_total: number;
  evidence_total: number;
  investigations_total: number;
  investigations_by_status: Record<string, number>;
  investigations_with_timing: number;
  avg_investigation_ms: number | null;
  total_iterations: number;
  documents_by_day: { date: string; documents: number; processed: number }[];
}

export interface EvaluationDashboardOut {
  generated_at: string;
  disclaimer: string;
  validation_note: string;
  datasets: EvaluationDatasetOut[];
  conflict_detection: EvaluationRunOut | null;
  evidence_verification: EvaluationRunOut | null;
  agents: AgentPerformanceSummary;
  documents: DocumentAnalyticsOut;
}

