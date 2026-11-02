import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FlaskConical, Search, ScanSearch, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { EvidenceAssessment } from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge, VerificationBadge } from "../components/badges";
import { ClaimVerificationPanel } from "../components/ClaimVerification";
import { SourceCredibilityListPanel } from "../components/SourceCredibility";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
} from "../components/ui";
import { cn, percent, relativeTime } from "../lib/format";

const ORIGINS = ["", "document", "user", "inferred"];
const TYPES = [
  "",
  "document_statement",
  "calibration_record",
  "timestamp",
  "measurement",
  "contextual",
  "user_supplied",
  "missing",
];
const VERIFICATION = [
  "",
  "unverified",
  "verified",
  "partially_verified",
  "unsupported",
  "requires_review",
];

export default function Evidence() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab =
    tabParam === "verification"
      ? "verification"
      : tabParam === "credibility"
      ? "credibility"
      : "records";
  const investigationParam = Number(params.get("investigation_id") ?? "");
  const documentParam = Number(params.get("document_id") ?? "");
  const investigationId = Number.isFinite(investigationParam) && investigationParam > 0
    ? investigationParam
    : undefined;
  const documentId = Number.isFinite(documentParam) && documentParam > 0
    ? documentParam
    : undefined;
  const [origin, setOrigin] = useState(params.get("origin") ?? "");
  const [type, setType] = useState(params.get("evidence_type") ?? "");
  const [verification, setVerification] = useState(params.get("verification_status") ?? "");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(1);

  const setTab = (next: "records" | "verification" | "credibility") => {
    const updated = new URLSearchParams(params);
    if (next === "records") updated.delete("tab");
    else updated.set("tab", next);
    setParams(updated, { replace: true });
  };

  const update = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    setPage(1);
  };

  const { data, loading, error, refetch } = useApi(
    () =>
      api.listEvidence({
        origin,
        evidence_type: type,
        verification_status: verification,
        q,
        page,
      }),
    [origin, type, verification, q, page],
    { enabled: tab === "records" }
  );

  const tabs = (
    <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
      <TabButton
        active={tab === "records"}
        onClick={() => setTab("records")}
        icon={<FlaskConical size={13} />}
        label="Evidence records"
      />
      <TabButton
        active={tab === "verification"}
        onClick={() => setTab("verification")}
        icon={<ScanSearch size={13} />}
        label="Claim verification"
      />
      <TabButton
        active={tab === "credibility"}
        onClick={() => setTab("credibility")}
        icon={<ShieldCheck size={13} />}
        label="Source credibility"
      />
    </div>
  );

  if (tab === "verification") {
    return (
      <div className="space-y-6">
        <SectionHeader
          title="Evidence & fact verification"
          subtitle="Check every extracted claim against the uploaded documents and recorded evidence."
          action={tabs}
        />
        {investigationId && (
          <p className="text-xs text-[var(--color-faint)]">
            Showing verdicts for investigation #{investigationId}.{" "}
            <Link
              to="/evidence?tab=verification"
              className="text-[var(--color-primary-soft)] hover:underline"
            >
              Clear investigation scope
            </Link>
          </p>
        )}
        <ClaimVerificationPanel
          investigationId={investigationId}
          documentId={documentId}
        />
      </div>
    );
  }

  if (tab === "credibility") {
    return (
      <div className="space-y-6">
        <SectionHeader
          title="Source credibility"
          subtitle="Authenticity, provenance, evidence quality and cross-source consistency assessed from stored records."
          action={tabs}
        />
        {investigationId && (
          <p className="text-xs text-[var(--color-faint)]">
            Showing sources for investigation #{investigationId}.{" "}
            <Link
              to="/evidence?tab=credibility"
              className="text-[var(--color-primary-soft)] hover:underline"
            >
              Clear investigation scope
            </Link>
          </p>
        )}
        <SourceCredibilityListPanel
          investigationId={investigationId}
          documentId={documentId}
        />
      </div>
    );
  }

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;
  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Evidence"
        subtitle="Every item that bears on a conflict, with its provenance and reliability."
        action={tabs}
      />

      <Card className="flex flex-wrap items-center gap-3">
        <FilterSelect value={origin} onChange={update(setOrigin)} options={ORIGINS} all="All origins" />
        <FilterSelect value={type} onChange={update(setType)} options={TYPES} all="All types" />
        <FilterSelect
          value={verification}
          onChange={update(setVerification)}
          options={VERIFICATION}
          all="All verification states"
        />
        <div className="ml-auto flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
          <Search size={14} className="text-[var(--color-faint)]" />
          <input
            value={q}
            onChange={(e) => update(setQ)(e.target.value)}
            placeholder="Search evidence…"
            className="w-52 bg-transparent text-sm outline-none placeholder:text-[var(--color-faint)]"
          />
        </div>
      </Card>

      {items.length === 0 ? (
        <EmptyState
          icon={<FlaskConical size={22} />}
          title="No evidence"
          description="Evidence is gathered by the Evidence Collector and Investigator agents."
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((e) => (
            <Card key={e.id} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={e.origin === "user" ? "violet" : "info"}>{e.origin}</Badge>
                <Badge tone="neutral">{e.evidence_type}</Badge>
                <VerificationBadge status={e.verification_status} />
                <Link
                  to={`/conflicts/${e.conflict_id}`}
                  className="ml-auto text-[11px] text-[var(--color-faint)] hover:text-[var(--color-primary-soft)]"
                >
                  C{e.conflict_id}
                </Link>
              </div>
              <p className="text-sm text-[var(--color-ink)]">{e.description}</p>
              <div className="flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
                {e.document_filename && <span>source: {e.document_filename}</span>}
                <span>relevance {percent(e.relevance_score)}</span>
                <span>reliability {percent(e.reliability_score)}</span>
                <span>directness {percent(e.directness)}</span>
                <span>{relativeTime(e.created_at)}</span>
              </div>
              {(e.supports_hypothesis_id || e.contradicts_hypothesis_id) && (
                <div className="flex flex-wrap gap-2 text-[11px]">
                  {e.supports_hypothesis_id && (
                    <Badge tone="success">supports H{e.supports_hypothesis_id}</Badge>
                  )}
                  {e.contradicts_hypothesis_id && (
                    <Badge tone="danger">contradicts H{e.contradicts_hypothesis_id}</Badge>
                  )}
                </div>
              )}
              {e.assessment && <AssessmentPanel assessment={e.assessment} />}
            </Card>
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
    </div>
  );
}

function AssessmentPanel({ assessment }: { assessment: EvidenceAssessment }) {
  const factors = Object.entries(assessment.factors);
  return (
    <details className="mt-1 rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-2 text-[11px]">
      <summary className="cursor-pointer select-none text-[var(--color-muted)]">
        Evidence assessment ·{" "}
        <span className="font-medium text-[var(--color-ink)]">
          {percent(assessment.overall_score)}
        </span>{" "}
        ({assessment.overall_label})
      </summary>
      <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
        {factors.map(([name, factor]) => (
          <div key={name} title={factor.explanation} className="flex items-center justify-between gap-2">
            <span className="capitalize text-[var(--color-faint)]">
              {name.replace(/_/g, " ")}
            </span>
            <span className="text-[var(--color-muted)]">{factor.label}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[var(--color-faint)]">
        Source reliability:{" "}
        <span className="text-[var(--color-muted)]">{assessment.source_reliability.label}</span>.{" "}
        {assessment.source_reliability.note}
      </p>
      {assessment.missing_information.length > 0 && (
        <p className="mt-1 text-[var(--color-faint)]">
          Missing information: {assessment.missing_information.join(" ")}
        </p>
      )}
      <p className="mt-1 text-[var(--color-faint)]">{assessment.caveat}</p>
    </details>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
        active
          ? "bg-[var(--color-primary)]/15 text-[var(--color-primary-soft)]"
          : "text-[var(--color-muted)] hover:text-[var(--color-ink)]"
      )}
    >
      {icon} {label}
    </button>
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
          {o ? o.replace(/_/g, " ") : all}
        </option>
      ))}
    </select>
  );
}
