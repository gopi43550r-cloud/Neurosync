import type {
  ActivityOut,
  AgentStatusOut,
  AuditEventOut,
  BlackboardEventOut,
  BlackboardRelationOut,
  BlackboardSnapshot,
  ClaimOut,
  ConflictDetail,
  ConflictOut,
  ConnectedRecordOut,
  DocumentDetail,
  DocumentOut,
  DocumentUploadResponse,
  EvidenceOut,
  FactVerificationList,
  FactVerificationOut,
  FactVerificationSummary,
  SourceCredibilityList,
  SourceCredibilityOut,
  ChatAnswer,
  ChatSuggestions,
  HealthInfo,
  HumanReviewOut,
  HypothesisOut,
  HypothesisRanking,
  InvestigationOut,
  DemoLoadResponse,
  KnowledgeGraph,
  Page,
  ReevaluationSummary,
  ReportOut,
  ReasoningSettings,
  ReviewDecision,
  ReviewResultOut,
  TraceResponse,
} from "./types";

// In dev, Vite proxies /api to the backend. In production, either serve the SPA
// from the same origin behind a reverse proxy that forwards /api (leave
// VITE_API_URL unset), or point VITE_API_URL at the API origin at build time.
// An empty/whitespace value falls back to the same-origin "/api" prefix.
const configuredApiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
const API_BASE = configuredApiUrl ? configuredApiUrl.replace(/\/$/, "") : "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json", ...(init?.headers || {}) }
        : init?.headers,
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
      if (Array.isArray(detail)) detail = detail.map((d: any) => d.msg).join("; ");
    } catch {
      /* ignore */
    }
    throw new ApiError(String(detail), res.status);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.append(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<HealthInfo>("/health"),
  config: () =>
    request<{
      app_name: string;
      version: string;
      mode: string;
      ai_configured: boolean;
      max_upload_mb: number;
      scheduler_weights: Record<string, number>;
      default_iteration_limit: number;
      default_min_evidence: number;
    }>("/config"),

  // Reasoning mode (LLM)
  reasoningSettings: () => request<ReasoningSettings>("/settings/reasoning"),
  updateReasoningMode: (mode: "deterministic" | "ai_assisted") =>
    request<ReasoningSettings>("/settings/reasoning", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),

  // Blackboard
  snapshot: (params: { days?: number } = {}) =>
    request<BlackboardSnapshot>(`/blackboard/snapshot${qs(params)}`),
  blackboardState: () =>
    request<{ counts: any; graph: any }>("/blackboard"),
  blackboardEvents: (
    params: {
      page?: number;
      page_size?: number;
      investigation_id?: number;
      event_type?: string;
      agent_name?: string;
      entity_type?: string;
      entity_id?: number;
    } = {}
  ) => request<Page<BlackboardEventOut>>(`/blackboard/events${qs(params)}`),
  blackboardRelations: (
    params: {
      page?: number;
      page_size?: number;
      investigation_id?: number;
      record_type?: string;
      record_id?: number;
      relation_type?: string;
    } = {}
  ) => request<Page<BlackboardRelationOut>>(`/blackboard/relations${qs(params)}`),
  blackboardConnected: (recordType: string, recordId: number, investigationId?: number) =>
    request<ConnectedRecordOut[]>(
      `/blackboard/connected/${recordType}/${recordId}${qs({ investigation_id: investigationId })}`
    ),
  blackboardTrace: (recordType: string, recordId: number, investigationId?: number) =>
    request<TraceResponse>(
      `/blackboard/trace/${recordType}/${recordId}${qs({ investigation_id: investigationId })}`
    ),
  reevaluate: (investigationId?: number) =>
    request<ReevaluationSummary>(
      `/blackboard/reevaluate${qs({ investigation_id: investigationId })}`,
      { method: "POST" }
    ),

  // Knowledge graph
  knowledgeGraph: (params: {
    investigation_id?: number;
    record_type?: string[];
    relation_type?: string[];
  } = {}) => {
    const sp = new URLSearchParams();
    if (params.investigation_id != null) sp.append("investigation_id", String(params.investigation_id));
    (params.record_type ?? []).forEach((t) => sp.append("record_type", t));
    (params.relation_type ?? []).forEach((t) => sp.append("relation_type", t));
    const s = sp.toString();
    return request<KnowledgeGraph>(`/knowledge-graph${s ? `?${s}` : ""}`);
  },

  // Documents
  listDocuments: (params: { page?: number; page_size?: number } = {}) =>
    request<Page<DocumentOut>>(`/documents${qs(params)}`),
  getDocument: (id: number) => request<DocumentDetail>(`/documents/${id}`),
  uploadDocuments: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<DocumentUploadResponse[]>("/documents/upload", {
      method: "POST",
      body: fd,
    });
  },
  reprocessDocument: (id: number) =>
    request<DocumentDetail>(`/documents/${id}/reprocess`, { method: "POST" }),
  deleteDocument: (id: number) =>
    request<{ message: string }>(`/documents/${id}`, { method: "DELETE" }),

  // Claims
  listClaims: (
    params: {
      page?: number;
      page_size?: number;
      document_id?: number;
      subject?: string;
      claim_type?: string;
      q?: string;
    } = {}
  ) => request<Page<ClaimOut>>(`/claims${qs(params)}`),

  // Fact verification (claim-level, evidence-grounded)
  getClaimVerification: (claimId: number, useLlm = false) =>
    request<FactVerificationOut>(
      `/claims/${claimId}/verification${qs({ use_llm: useLlm })}`
    ),
  listClaimVerifications: (
    params: {
      page?: number;
      page_size?: number;
      document_id?: number;
      claim_type?: string;
      verdict?: string;
      q?: string;
      use_llm?: boolean;
    } = {}
  ) => request<FactVerificationList>(`/verification/claims${qs(params)}`),
  verificationSummary: (
    params: { document_id?: number; claim_type?: string; q?: string } = {}
  ) => request<FactVerificationSummary>(`/verification/summary${qs(params)}`),
  investigationClaimVerifications: (
    investigationId: number,
    params: {
      page?: number;
      page_size?: number;
      verdict?: string;
      use_llm?: boolean;
    } = {}
  ) =>
    request<FactVerificationList>(
      `/investigations/${investigationId}/claim-verifications${qs(params)}`
    ),

  // Source credibility (stored-record analysis, computed on read)
  getDocumentCredibility: (documentId: number) =>
    request<SourceCredibilityOut>(`/documents/${documentId}/credibility`),
  listSourceCredibility: (
    params: {
      page?: number;
      page_size?: number;
      q?: string;
      level?: string;
      unknown_only?: boolean;
      document_id?: number;
    } = {}
  ) => request<SourceCredibilityList>(`/source-credibility${qs(params)}`),
  investigationSourceCredibility: (
    investigationId: number,
    params: {
      page?: number;
      page_size?: number;
      level?: string;
      unknown_only?: boolean;
    } = {}
  ) =>
    request<SourceCredibilityList>(
      `/investigations/${investigationId}/source-credibility${qs(params)}`
    ),

  // Investigation chat (grounded in this investigation's stored records)
  investigationChat: (
    investigationId: number,
    payload: {
      question: string;
      conflict_id?: number;
      claim_id?: number;
      hypothesis_id?: number;
      document_id?: number;
    }
  ) =>
    request<ChatAnswer>(`/investigations/${investigationId}/chat`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  investigationChatSuggestions: (investigationId: number) =>
    request<ChatSuggestions>(
      `/investigations/${investigationId}/chat/suggestions`
    ),

  // Conflicts
  listConflicts: (
    params: {
      page?: number;
      page_size?: number;
      severity?: string;
      conflict_type?: string;
      status?: string;
      document_id?: number;
      q?: string;
    } = {}
  ) => request<Page<ConflictOut>>(`/conflicts${qs(params)}`),
  getConflict: (id: number) => request<ConflictDetail>(`/conflicts/${id}`),
  updateConflict: (
    id: number,
    payload: { status?: string; severity?: string; resolution_summary?: string }
  ) =>
    request<ConflictOut>(`/conflicts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  rankHypotheses: (conflictId: number) =>
    request<HypothesisRanking[]>(`/conflicts/${conflictId}/hypotheses/ranking`),
  evidenceGaps: (conflictId: number) =>
    request<string[]>(`/conflicts/${conflictId}/evidence-gaps`),
  conflictReviews: (conflictId: number) =>
    request<HumanReviewOut[]>(`/conflicts/${conflictId}/reviews`),
  conclusionReviews: (conclusionId: number) =>
    request<HumanReviewOut[]>(`/conclusions/${conclusionId}/reviews`),

  // Human review
  submitReview: (
    conclusionId: number,
    payload: { decision: ReviewDecision; reviewer?: string; note?: string }
  ) =>
    request<ReviewResultOut>(`/conclusions/${conclusionId}/review`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listReviews: (params: { page?: number; page_size?: number; investigation_id?: number } = {}) =>
    request<Page<HumanReviewOut>>(`/reviews${qs(params)}`),

  // Audit trail
  listAudit: (
    params: {
      page?: number;
      page_size?: number;
      entity_type?: string;
      entity_id?: number;
      investigation_id?: number;
      conflict_id?: number;
    } = {}
  ) => request<Page<AuditEventOut>>(`/audit${qs(params)}`),

  // Evidence
  listEvidence: (
    params: {
      page?: number;
      page_size?: number;
      conflict_id?: number;
      origin?: string;
      evidence_type?: string;
      verification_status?: string;
      q?: string;
    } = {}
  ) => request<Page<EvidenceOut>>(`/evidence${qs(params)}`),
  addEvidence: (
    conflictId: number,
    payload: {
      description: string;
      evidence_type?: string;
      source_reference?: string;
      relevance_score?: number;
      reliability_score?: number;
      supports_hypothesis_id?: number | null;
      contradicts_hypothesis_id?: number | null;
    }
  ) =>
    request<EvidenceOut>(`/conflicts/${conflictId}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Hypotheses
  listHypotheses: (
    params: {
      page?: number;
      page_size?: number;
      conflict_id?: number;
      status?: string;
      q?: string;
    } = {}
  ) => request<Page<HypothesisOut>>(`/hypotheses${qs(params)}`),
  createHypothesis: (
    conflictId: number,
    payload: { title: string; explanation?: string }
  ) =>
    request<HypothesisOut>(`/conflicts/${conflictId}/hypotheses`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reviewHypothesis: (id: number, action: string, note = "") =>
    request<HypothesisOut>(`/hypotheses/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ action, note }),
    }),

  // Investigations
  listInvestigations: (params: { page?: number; page_size?: number; status?: string } = {}) =>
    request<Page<InvestigationOut>>(`/investigations${qs(params)}`),
  getInvestigation: (id: number) => request<InvestigationOut>(`/investigations/${id}`),
  createInvestigation: (payload: {
    name: string;
    research_question?: string;
    document_ids?: number[];
    conflict_ids?: number[];
    iteration_limit?: number;
    min_evidence_threshold?: number;
    enable_llm?: boolean;
  }) =>
    request<InvestigationOut>("/investigations", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  investigationAction: (id: number, action: "start" | "pause" | "resume" | "cancel") =>
    request<InvestigationOut>(`/investigations/${id}/${action}`, { method: "POST" }),
  activity: (id: number) => request<ActivityOut[]>(`/investigations/${id}/activity`),
  report: (id: number) => request<ReportOut>(`/investigations/${id}/report`),
  reportExportUrl: (id: number, format: "markdown" | "json" | "pdf") =>
    `${API_BASE}/investigations/${id}/report/export?format=${format}`,
  eventsUrl: (id: number) => `${API_BASE}/investigations/${id}/events`,

  // Agents
  agents: () => request<AgentStatusOut[]>("/agents"),

  // Demo
  loadDemo: (autoStart = false) =>
    request<DemoLoadResponse>(`/demo/load${qs({ auto_start: autoStart })}`, {
      method: "POST",
    }),
  resetDemo: () =>
    request<{ message: string }>("/demo/reset", { method: "POST" }),

  // Search
  search: (q: string) =>
    request<Record<string, { id: number; label: string }[]>>(`/search${qs({ q })}`),
};

export { API_BASE };
