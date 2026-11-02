import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  CheckCircle2,
  FileText,
  HelpCircle,
  MinusCircle,
  Search,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api } from "../api/client";
import type {
  FactVerificationList,
  FactVerificationOut,
  VerificationEvidenceItem,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge, FactVerdictBadge } from "../components/badges";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
  Spinner,
} from "../components/ui";
import { cn, percent, relativeTime, titleCase } from "../lib/format";

const VERDICTS = ["", "supported", "contradicted", "partially_supported", "unverified"];
const CLAIM_TYPES = ["", "measurement", "state", "event", "statement"];

/**
 * Claim-level fact verification.
 *
 * Every value shown here comes from the backend verifier, which compares the
 * claim only with real claims, evidence rows and document sentences. No
 * evidence is generated in the browser; missing material is shown as
 * "Unverified" plus an explicit missing-information list.
 */
export function ClaimVerificationPanel({
  investigationId,
  documentId,
}: {
  investigationId?: number;
  documentId?: number;
}) {
  const [verdict, setVerdict] = useState("");
  const [claimType, setClaimType] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const reset = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    setPage(1);
  };

  const state = useApi<FactVerificationList>(
    () =>
      investigationId
        ? api.investigationClaimVerifications(investigationId, {
            page,
            page_size: 10,
            verdict: verdict || undefined,
          })
        : api.listClaimVerifications({
            page,
            page_size: 10,
            verdict: verdict || undefined,
            claim_type: claimType || undefined,
            q: q || undefined,
            document_id: documentId,
          }),
    [investigationId, documentId, verdict, claimType, q, page]
  );

  if (state.loading && !state.data) return <Loading label="Verifying claims against the documents…" />;
  if (state.error && !state.data) {
    return <ErrorState message={state.error} onRetry={state.refetch} />;
  }
  const data = state.data;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <VerdictStat label="Supported" value={data?.counts.supported ?? 0} tone="success" />
        <VerdictStat label="Contradicted" value={data?.counts.contradicted ?? 0} tone="danger" />
        <VerdictStat
          label="Partially supported"
          value={data?.counts.partially_supported ?? 0}
          tone="warning"
        />
        <VerdictStat label="Unverified" value={data?.counts.unverified ?? 0} tone="neutral" />
      </div>

      <Card className="flex flex-wrap items-center gap-3">
        <FilterSelect
          value={verdict}
          onChange={reset(setVerdict)}
          options={VERDICTS}
          all="All verdicts"
        />
        {!investigationId && (
          <FilterSelect
            value={claimType}
            onChange={reset(setClaimType)}
            options={CLAIM_TYPES}
            all="All claim types"
          />
        )}
        {investigationId ? (
          <span className="text-xs text-[var(--color-muted)]">
            Scoped to{" "}
            <Link
              to={`/investigations/${investigationId}`}
              className="text-[var(--color-primary-soft)] hover:underline"
            >
              investigation #{investigationId}
            </Link>
          </span>
        ) : (
          <div className="ml-auto flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
            <Search size={14} className="text-[var(--color-faint)]" />
            <input
              value={q}
              onChange={(e) => reset(setQ)(e.target.value)}
              placeholder="Search claims…"
              className="w-52 bg-transparent text-sm outline-none placeholder:text-[var(--color-faint)]"
            />
          </div>
        )}
        <span className="ml-auto text-xs text-[var(--color-faint)]">
          {data?.total ?? 0} claim(s) · {data?.documents_considered ?? 0} document(s)
        </span>
      </Card>

      {!data || data.items.length === 0 ? (
        <EmptyState
          icon={<HelpCircle size={22} />}
          title="No claims to verify"
          description={
            data?.total === 0 && verdict
              ? "No claim in this scope received that verdict."
              : "Claims are extracted from uploaded documents. Upload a document or run an investigation first."
          }
        />
      ) : (
        <div className="space-y-3">
          {data.items.map((item) => (
            <ClaimCard key={item.claim_id ?? item.claim_text} item={item} />
          ))}
        </div>
      )}

      {data && (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          onPageChange={setPage}
        />
      )}

      {(data?.methodology || data?.caveat) && (
        <details className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3 text-xs text-[var(--color-muted)]">
          <summary className="cursor-pointer select-none">How claims are verified</summary>
          {data?.methodology && <p className="mt-2">{data.methodology}</p>}
          {data?.caveat && <p className="mt-1 text-[var(--color-faint)]">{data.caveat}</p>}
        </details>
      )}
    </div>
  );
}

function VerdictStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "danger" | "warning" | "neutral";
}) {
  const tones = {
    success: "text-[var(--color-success)]",
    danger: "text-[var(--color-danger)]",
    warning: "text-[var(--color-warning)]",
    neutral: "text-[var(--color-faint)]",
  };
  return (
    <Card className="flex flex-col gap-0.5 p-4">
      <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-faint)]">
        {label}
      </span>
      <span className={cn("text-2xl font-semibold tabular-nums", tones[tone])}>{value}</span>
    </Card>
  );
}

function ClaimCard({ item }: { item: FactVerificationOut }) {
  const [ai, setAi] = useState<FactVerificationOut | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const shown = ai ?? item;

  const explainWithAi = async () => {
    if (!item.claim_id) return;
    setAiBusy(true);
    setAiError(null);
    try {
      setAi(await api.getClaimVerification(item.claim_id, true));
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <FactVerdictBadge verdict={shown.verdict} />
        <Badge tone="neutral">{titleCase(shown.claim_type)}</Badge>
        {shown.subject && <Badge tone="primary">{shown.subject}</Badge>}
        <span className="text-[11px] text-[var(--color-faint)]">
          extraction confidence {percent(shown.claim_confidence)}
        </span>
        <span className="ml-auto font-mono text-[11px] text-[var(--color-faint)]">
          claim #{shown.claim_id ?? "—"}
        </span>
      </div>

      <blockquote className="rounded-lg border-l-2 border-[var(--color-primary)]/60 bg-[var(--color-surface-2)]/50 px-3 py-2 text-sm text-[var(--color-ink)]">
        “{shown.claim_text}”
      </blockquote>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-faint)]">
        <span className="inline-flex items-center gap-1">
          <FileText size={12} /> {shown.source.text_location || "source unavailable"}
        </span>
        {shown.source.page != null && <Badge tone="info">page {shown.source.page}</Badge>}
        {shown.source.document_id != null && (
          <Link
            to={`/documents/${shown.source.document_id}`}
            className="inline-flex items-center gap-1 text-[var(--color-primary-soft)] hover:underline"
          >
            open document <ArrowUpRight size={11} />
          </Link>
        )}
        <span>verifier confidence {percent(shown.confidence)}</span>
        <span>checked {relativeTime(shown.analyzed_at)}</span>
      </div>

      <p className="text-sm text-[var(--color-ink)]">{shown.summary}</p>
      <p className="text-xs leading-relaxed text-[var(--color-muted)]">{shown.explanation}</p>

      <div className="flex flex-wrap gap-2 text-[11px]">
        <Badge tone="success">{shown.supporting_evidence.length} supporting</Badge>
        <Badge tone="danger">{shown.contradicting_evidence.length} contradicting</Badge>
        <Badge tone="neutral">{shown.neutral_evidence.length} contextual</Badge>
        <Badge tone="warning">{shown.missing_information.length} missing</Badge>
        <Badge tone="info">{shown.claims_compared} comparison(s)</Badge>
      </div>

      <details className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/30 p-3 text-xs">
        <summary className="cursor-pointer select-none font-medium text-[var(--color-muted)]">
          Evidence, sources and missing information
        </summary>

        <div className="mt-3 space-y-3">
          <EvidenceGroup
            title="Supporting evidence"
            icon={<CheckCircle2 size={14} className="text-[var(--color-success)]" />}
            items={shown.supporting_evidence}
          />
          <EvidenceGroup
            title="Contradicting evidence"
            icon={<XCircle size={14} className="text-[var(--color-danger)]" />}
            items={shown.contradicting_evidence}
          />
          <EvidenceGroup
            title="Contextual evidence (not decisive)"
            icon={<MinusCircle size={14} className="text-[var(--color-faint)]" />}
            items={shown.neutral_evidence}
          />

          <div>
            <p className="mb-1 font-medium text-[var(--color-muted)]">Missing information</p>
            {shown.missing_information.length === 0 ? (
              <p className="text-[var(--color-faint)]">
                No specific gap was identified for this claim.
              </p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-[var(--color-muted)]">
                {shown.missing_information.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            )}
          </div>

          {shown.analysis_notes.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-[var(--color-muted)]">Analysis notes</p>
              <ul className="list-disc space-y-1 pl-5 text-[var(--color-faint)]">
                {shown.analysis_notes.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--color-border-soft)] pt-2">
            <Button size="sm" variant="outline" onClick={explainWithAi} disabled={aiBusy}>
              {aiBusy ? <Spinner /> : <Sparkles size={13} />} Explain with AI
            </Button>
            <span className="text-[11px] text-[var(--color-faint)]">
              {shown.method === "ai_assisted"
                ? "AI-assisted rationale was accepted; all citations were validated."
                : "The verdict is deterministic. AI can only rewrite the rationale, never the classification."}
            </span>
          </div>
          {aiError && <p className="text-[10px] text-[var(--color-danger)]">{aiError}</p>}
        </div>
      </details>
    </Card>
  );
}

function EvidenceGroup({
  title,
  icon,
  items,
}: {
  title: string;
  icon: ReactNode;
  items: VerificationEvidenceItem[];
}) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1.5 font-medium text-[var(--color-muted)]">
        {icon} {title}
      </p>
      {items.length === 0 ? (
        <p className="text-[var(--color-faint)]">None found.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((e, i) => (
            <li
              key={`${e.kind}-${e.record_id ?? i}`}
              className="rounded border border-[var(--color-border-soft)] bg-[var(--color-surface)]/60 p-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={e.independence === "independent" ? "primary" : "neutral"}>
                  {titleCase(e.independence || "unknown")}
                </Badge>
                <Badge tone="neutral">{e.kind}</Badge>
                {e.source.page != null && <Badge tone="info">page {e.source.page}</Badge>}
                <span className="ml-auto text-[10px] text-[var(--color-faint)]">
                  {e.source.text_location}
                </span>
              </div>
              <p className="mt-1 text-[var(--color-ink)]">“{e.text}”</p>
              {e.reason && <p className="mt-1 text-[var(--color-muted)]">{e.reason}</p>}
              {e.source.document_id != null && (
                <Link
                  to={`/documents/${e.source.document_id}`}
                  className="mt-1 inline-flex items-center gap-1 text-[var(--color-primary-soft)] hover:underline"
                >
                  open source <ArrowUpRight size={10} />
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
  all,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  all: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o ? titleCase(o) : all}
        </option>
      ))}
    </select>
  );
}

/** Compact verification summary for the investigation workspace. */
export function InvestigationVerificationSummary({
  investigationId,
}: {
  investigationId: number;
}) {
  const { data, loading, error } = useApi(
    () => api.investigationClaimVerifications(investigationId, { page_size: 1 }),
    [investigationId]
  );

  return (
    <Card>
      <SectionHeader
        title="Claim verification"
        subtitle="Every extracted claim compared with the investigation's uploaded documents."
        action={
          <Link to={`/evidence?tab=verification&investigation_id=${investigationId}`}>
            <Button size="sm" variant="outline">
              View verdicts <ArrowUpRight size={13} />
            </Button>
          </Link>
        }
      />
      {loading && !data ? (
        <p className="py-4 text-sm text-[var(--color-muted)]">Verifying claims…</p>
      ) : error && !data ? (
        <p className="text-sm text-[var(--color-danger)]">{error}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Badge tone="success">{data?.counts.supported ?? 0} supported</Badge>
            <Badge tone="danger">{data?.counts.contradicted ?? 0} contradicted</Badge>
            <Badge tone="warning">
              {data?.counts.partially_supported ?? 0} partially supported
            </Badge>
            <Badge tone="neutral">{data?.counts.unverified ?? 0} unverified</Badge>
          </div>
          <p className="mt-2 text-xs text-[var(--color-faint)]">
            {data?.total ?? 0} claim(s) checked against {data?.documents_considered ?? 0}{" "}
            document(s). Verdicts are recomputed from the current records, so they never go stale.
          </p>
        </>
      )}
    </Card>
  );
}
