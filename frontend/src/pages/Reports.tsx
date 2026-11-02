import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Download,
  FileJson,
  FileText,
  Link2,
  Printer,
  ScrollText,
  TriangleAlert,
} from "lucide-react";
import { api } from "../api/client";
import type {
  ReportClaim,
  ReportData,
  ReportEvidenceByClaim,
  ReportEvidenceRef,
  ReportEvidenceRefLite,
  ReportOut,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import {
  Badge,
  ConflictStatusBadge,
  HypothesisStatusBadge,
  InvestigationStatusBadge,
  SeverityBadge,
  VerificationBadge,
} from "../components/badges";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  SectionHeader,
} from "../components/ui";
import { formatBytes, formatDate, percent, relativeTime, titleCase } from "../lib/format";

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const investigations = useApi(() => api.listInvestigations({ page_size: 100 }), []);
  const initial = params.get("investigation");
  const [selected, setSelected] = useState<number | null>(
    initial ? Number(initial) : null
  );

  useEffect(() => {
    if (selected == null && investigations.data?.items.length) {
      const completed = investigations.data.items.find((i) => i.status === "completed");
      setSelected((completed ?? investigations.data.items[0]).id);
    }
  }, [investigations.data, selected]);

  const report = useApi(
    () => (selected != null ? api.report(selected) : Promise.resolve(null)),
    [selected],
    { enabled: selected != null }
  );

  const pick = (id: number) => {
    setSelected(id);
    setParams({ investigation: String(id) });
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Reports"
        subtitle="Transparent, auditable and exportable summaries of each investigation. Every claim, conflict and piece of evidence links back to the record it came from."
      />

      {investigations.loading && !investigations.data ? (
        <Loading />
      ) : (investigations.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon={<ScrollText size={22} />}
          title="No investigations to report on"
          description="Run an investigation first."
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-2 print:hidden">
            {investigations.data!.items.map((inv) => (
              <button
                key={inv.id}
                onClick={() => pick(inv.id)}
                className={`rounded-full border px-3 py-1.5 text-xs transition ${
                  selected === inv.id
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/20 text-[var(--color-ink)]"
                    : "border-[var(--color-border)] text-[var(--color-muted)] hover:border-[var(--color-primary)]/50"
                }`}
              >
                {inv.name}
                <span className="ml-2 text-[10px] text-[var(--color-faint)]">
                  {titleCase(inv.status)}
                </span>
              </button>
            ))}
          </div>

          {report.loading && !report.data ? (
            <Loading label="Building report…" />
          ) : report.error ? (
            <ErrorState message={report.error} onRetry={report.refetch} />
          ) : report.data ? (
            <ReportView report={report.data} />
          ) : null}
        </>
      )}
    </div>
  );
}

function ReportView({ report }: { report: ReportOut }) {
  const data = report.json_data;
  const inv = data.investigation;

  return (
    <>
      <PrintStyles />
      <Card className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold">{report.title}</h2>
              <InvestigationStatusBadge status={inv.status} />
              {inv.is_demo && <Badge tone="info">demonstration data</Badge>}
            </div>
            <p className="mt-1 text-sm text-[var(--color-muted)]">{report.objective}</p>
            <p className="mt-1 text-xs text-[var(--color-faint)]">
              Investigation id {report.investigation_id} · generated{" "}
              {relativeTime(report.generated_at)} · stop reason: {report.stopping_reason}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 print:hidden">
            <Badge tone={confidenceTone(report.confidence)}>
              confidence {percent(report.confidence)}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer size={14} /> Print
            </Button>
            <ExportLink
              href={api.reportExportUrl(report.investigation_id, "pdf")}
              label="PDF"
              icon={<Download size={14} />}
            />
            <ExportLink
              href={api.reportExportUrl(report.investigation_id, "markdown")}
              label="Markdown"
              icon={<FileText size={14} />}
            />
            <ExportLink
              href={api.reportExportUrl(report.investigation_id, "json")}
              label="JSON"
              icon={<FileJson size={14} />}
            />
          </div>
        </div>

        <p className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm text-[var(--color-muted)]">
          {report.confidence_explanation}
        </p>

        {report.warnings.length > 0 && (
          <div className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 p-3">
            <p className="mb-1 flex items-center gap-2 text-sm font-medium text-[var(--color-warning)]">
              <TriangleAlert size={15} /> Read with care
            </p>
            <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-muted)]">
              {report.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <div id="report-printable" className="space-y-4">
        <DocumentsSection data={data} />
        <ClaimsSection claims={data.claims} />
        <ConflictsSection data={data} />
        <EvidenceByClaimSection entries={data.evidence_by_claim} />
        <HypothesesSection data={data} />
        <VerificationSection data={data} />
        <ConclusionSection data={data} />
        <MissingEvidenceSection data={data} />
        <HumanReviewSection data={data} />
        <ActivitySection data={data} />
        <LimitationsSection data={data} />
        <AuditSection data={data} />
      </div>
    </>
  );
}

function PrintStyles() {
  return (
    <style>{`
@media print {
  body * { visibility: hidden !important; }
  #report-printable, #report-printable * { visibility: visible !important; }
  #report-printable { position: absolute; inset: 0; width: 100%; }
  .print\\:hidden { display: none !important; }
}
`}</style>
  );
}

function ExportLink({
  href,
  label,
  icon,
}: {
  href: string;
  label: string;
  icon: ReactNode;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      <Button variant="outline" size="sm">
        {icon} {label}
      </Button>
    </a>
  );
}

function confidenceTone(value: number): "success" | "warning" | "danger" {
  return value >= 0.7 ? "success" : value >= 0.45 ? "warning" : "danger";
}

function KindBadge({ kind }: { kind: string }) {
  return kind === "inferred" ? (
    <Badge tone="violet">inferred</Badge>
  ) : (
    <Badge tone="info">observed</Badge>
  );
}

function SourceLink({ to, children }: { to: string | null; children: ReactNode }) {
  if (!to) return <span>{children}</span>;
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1 text-[var(--color-primary-soft)] hover:underline"
    >
      <Link2 size={12} /> {children}
    </Link>
  );
}

function ReportSectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Card className="space-y-3">
      <div>
        <h3 className="text-base font-semibold text-[var(--color-ink)]">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-[var(--color-muted)]">{subtitle}</p>}
      </div>
      {children}
    </Card>
  );
}

// ---------------------------------------------------------------- documents
function DocumentsSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Documents Analyzed"
      subtitle={`${data.documents.length} document(s). Filenames are reported observations.`}
    >
      <ul className="space-y-2">
        {data.documents.map((d) => (
          <li
            key={d.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
          >
            <div className="flex flex-wrap items-center gap-2">
              <KindBadge kind={d.kind} />
              <SourceLink to={d.link}>{d.filename}</SourceLink>
              {d.is_demo && <Badge tone="info">demo</Badge>}
            </div>
            <span className="text-xs text-[var(--color-faint)]">
              {d.file_type} · {formatBytes(d.file_size)} · {d.claim_count} claim(s) ·{" "}
              {titleCase(d.status)}
            </span>
          </li>
        ))}
      </ul>
    </ReportSectionCard>
  );
}

// ------------------------------------------------------------------- claims
function ClaimsSection({ claims }: { claims: ReportClaim[] }) {
  return (
    <ReportSectionCard
      title="Claims Extracted"
      subtitle="Reported assertions extracted from the documents. These are observations, not established facts."
    >
      {claims.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">No claims were extracted.</p>
      ) : (
        <ul className="space-y-2">
          {claims.map((c) => (
            <li
              key={c.id}
              className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">claim {c.id}</Badge>
                <KindBadge kind={c.kind} />
                <Badge tone="primary">{titleCase(c.claim_type)}</Badge>
                {c.numeric_value !== null && (
                  <Badge tone="info">
                    {c.numeric_value}
                    {c.unit ? ` ${c.unit}` : ""}
                  </Badge>
                )}
              </div>
              <p className="mt-1.5 text-[var(--color-ink)]">{c.claim_text}</p>
              <p className="mt-1 text-xs text-[var(--color-faint)]">
                Source: <SourceLink to={c.document_link}>{c.document_filename ?? "—"}</SourceLink>
                {c.source_reference ? ` · ${c.source_reference}` : ""}
                {c.source_location ? ` · ${c.source_location}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}

// ---------------------------------------------------------------- conflicts
function ConflictsSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Conflicts Detected"
      subtitle="Recorded contradictions between claims. The conflict itself is an observation."
    >
      {data.conflicts.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">No conflicts were detected.</p>
      ) : (
        <ul className="space-y-3">
          {data.conflicts.map((c) => (
            <li
              key={c.id}
              className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <SourceLink to={c.link}>Conflict {c.id}</SourceLink>
                <Badge tone="neutral">{titleCase(c.type)}</Badge>
                <SeverityBadge severity={c.severity} />
                <ConflictStatusBadge status={c.status} />
              </div>
              <p className="mt-1.5 text-[var(--color-ink)]">{c.description}</p>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                {[c.claim_a, c.claim_b].map(
                  (ref, i) =>
                    ref && (
                      <div
                        key={i}
                        className="rounded-md border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-2 text-xs"
                      >
                        <span className="font-medium text-[var(--color-muted)]">
                          Claim {ref.id}:
                        </span>{" "}
                        <span className="text-[var(--color-ink)]">{ref.text}</span>
                        <div className="mt-1 text-[var(--color-faint)]">
                          <SourceLink to={ref.document_link}>{ref.document_filename ?? "—"}</SourceLink>
                        </div>
                      </div>
                    )
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}

// --------------------------------------------------------- evidence by claim
function EvidenceRefList({
  items,
  empty,
}: {
  items: ReportEvidenceRef[];
  empty: string;
}) {
  if (items.length === 0) {
    return <p className="text-xs text-[var(--color-faint)]">{empty}</p>;
  }
  return (
    <ul className="space-y-1">
      {items.map((e) => (
        <li key={e.id} className="text-xs text-[var(--color-muted)]">
          <span className="font-medium text-[var(--color-ink)]">Evidence {e.id}</span>{" "}
          <Badge tone="neutral">{titleCase(e.evidence_type)}</Badge> {e.description}
          {e.document_filename && (
            <>
              {" "}
              · <SourceLink to={e.document_link}>{e.document_filename}</SourceLink>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function EvidenceByClaimSection({ entries }: { entries: ReportEvidenceByClaim[] }) {
  return (
    <ReportSectionCard
      title="Evidence For and Against Each Relevant Claim"
      subtitle="Supporting evidence is explicitly linked to the claim; contradicting evidence is linked to the opposing claim in the recorded conflict. No contradiction is invented."
    >
      {entries.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">
          No conflict-relevant claims were recorded.
        </p>
      ) : (
        <ul className="space-y-3">
          {entries.map((entry) => (
            <li
              key={entry.claim_id}
              className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="neutral">claim {entry.claim_id}</Badge>
                <span className="text-[var(--color-ink)]">{entry.claim_text}</span>
                <SourceLink to={entry.document_link}>source</SourceLink>
                <SourceLink to={entry.conflict_link}>conflict {entry.conflict_id}</SourceLink>
              </div>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-success)]">
                    Supporting
                  </p>
                  <EvidenceRefList items={entry.supporting_evidence} empty="None recorded." />
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-danger)]">
                    Contradicting
                  </p>
                  <EvidenceRefList items={entry.contradicting_evidence} empty="None recorded." />
                  <p className="mt-1 text-[10px] text-[var(--color-faint)]">{entry.basis}</p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}

// --------------------------------------------------------------- hypotheses
function HypoEvidenceList({
  refs,
  empty,
}: {
  refs: ReportEvidenceRefLite[];
  empty: string;
}) {
  const real = refs.filter((r) => r.exists);
  if (real.length === 0) return <span className="text-xs text-[var(--color-faint)]">{empty}</span>;
  return (
    <span className="text-xs text-[var(--color-muted)]">
      {real.map((r) => `Evidence ${r.id}`).join(", ")}
    </span>
  );
}

function HypothesesSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Competing Hypotheses"
      subtitle={`${data.hypotheses.length} proposed explanation(s). These are inferred, not observed. Ranked below by documented evidence weight.`}
    >
      {data.hypotheses.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">No hypotheses were proposed.</p>
      ) : (
        <ul className="space-y-3">
          {[...data.hypotheses]
            .sort((a, b) => b.support_score - a.support_score)
            .map((h) => (
              <li
                key={h.id}
                className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <KindBadge kind={h.kind} />
                  <span className="font-medium text-[var(--color-ink)]">{h.title}</span>
                  <HypothesisStatusBadge status={h.status} />
                  <Badge tone="neutral">
                    support {h.support_score.toFixed(2)} · confidence {h.confidence.toFixed(2)}
                  </Badge>
                  <SourceLink to={h.conflict_link}>conflict {h.conflict_id}</SourceLink>
                </div>
                {h.explanation && (
                  <p className="mt-1.5 text-[var(--color-muted)]">{h.explanation}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  <span className="text-xs text-[var(--color-muted)]">
                    Supporting: <HypoEvidenceList refs={h.supporting_evidence} empty="none" />
                  </span>
                  <span className="text-xs text-[var(--color-muted)]">
                    Contradicting: <HypoEvidenceList refs={h.contradicting_evidence} empty="none" />
                  </span>
                </div>
                {h.assumptions.length > 0 && (
                  <p className="mt-1 text-xs text-[var(--color-faint)]">
                    Assumptions: {h.assumptions.join("; ")}
                  </p>
                )}
                {h.missing_information.length > 0 && (
                  <p className="mt-0.5 text-xs text-[var(--color-faint)]">
                    Missing: {h.missing_information.join("; ")}
                  </p>
                )}
              </li>
            ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}

// ------------------------------------------------------------- verification
function VerificationSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Verification Results"
      subtitle="Quality indicators for each piece of evidence. Reliability and relevance are bounded indicators, not probabilities."
    >
      {data.verification.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">No evidence to verify.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[var(--color-faint)]">
              <tr className="border-b border-[var(--color-border-soft)]">
                <th className="py-1.5 pr-3 font-medium">Evidence</th>
                <th className="py-1.5 pr-3 font-medium">Type</th>
                <th className="py-1.5 pr-3 font-medium">Verification</th>
                <th className="py-1.5 pr-3 font-medium">Rel.</th>
                <th className="py-1.5 pr-3 font-medium">Relev.</th>
                <th className="py-1.5 pr-3 font-medium">Weight</th>
                <th className="py-1.5 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="text-[var(--color-muted)]">
              {data.verification.map((v) => (
                <tr key={v.evidence_id} className="border-b border-[var(--color-border-soft)]/60">
                  <td className="py-1.5 pr-3 text-[var(--color-ink)]">#{v.evidence_id}</td>
                  <td className="py-1.5 pr-3">{titleCase(v.evidence_type)}</td>
                  <td className="py-1.5 pr-3">
                    <VerificationBadge status={v.verification_status} />
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">{v.reliability_score.toFixed(2)}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{v.relevance_score.toFixed(2)}</td>
                  <td className="py-1.5 pr-3 tabular-nums">{v.weight.toFixed(2)}</td>
                  <td className="py-1.5">
                    <SourceLink to={v.document_link}>{v.document_filename ?? "—"}</SourceLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ReportSectionCard>
  );
}

// --------------------------------------------------------------- conclusion
function ConclusionSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Final Conclusion or Inconclusive Status"
      subtitle={`Overall confidence ${percent(data.confidence.value)}. ${data.confidence.basis}`}
    >
      {data.conclusions.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">
          No conclusion could be produced; the investigation is inconclusive.
        </p>
      ) : (
        <ul className="space-y-3">
          {data.conclusions.map((c) => (
            <li
              key={c.id}
              className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={c.is_inconclusive ? "warning" : "success"}>
                  {titleCase(c.decision_type)}
                </Badge>
                <Badge tone="neutral">confidence {c.confidence.toFixed(2)}</Badge>
                {c.conflict_link && <SourceLink to={c.conflict_link}>conflict {c.conflict_id}</SourceLink>}
              </div>
              <p className="mt-1.5 text-[var(--color-ink)]">{c.conclusion}</p>
              {c.supporting_evidence.filter((r) => r.exists).length > 0 && (
                <p className="mt-1 text-xs text-[var(--color-faint)]">
                  Based on evidence{" "}
                  {c.supporting_evidence
                    .filter((r) => r.exists)
                    .map((r) => `#${r.id}`)
                    .join(", ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-[var(--color-muted)]">{data.confidence.interpretation}</p>
    </ReportSectionCard>
  );
}

// ------------------------------------------------- missing evidence / open Qs
function MissingEvidenceSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Missing Evidence and Unresolved Questions"
      subtitle="Information whose absence limits confidence in any conclusion."
    >
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
            Evidence gaps
          </p>
          {data.evidence_gaps.length ? (
            <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-muted)]">
              {data.evidence_gaps.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">None recorded.</p>
          )}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
            Unresolved questions
          </p>
          {data.unresolved_questions.length ? (
            <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-muted)]">
              {data.unresolved_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">None recorded.</p>
          )}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
            Recommended next steps
          </p>
          <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-muted)]">
            {data.recommendations.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      </div>
    </ReportSectionCard>
  );
}

// -------------------------------------------------------------- human review
function HumanReviewSection({ data }: { data: ReportData }) {
  const status = data.human_review_status;
  return (
    <ReportSectionCard
      title="Human Review"
      subtitle="This report supports, but does not replace, professional judgement."
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={status.required ? "violet" : "success"}>{titleCase(status.status)}</Badge>
        <span className="text-[var(--color-muted)]">
          {status.decisions_recorded} decision(s) recorded
        </span>
        {status.conflicts_awaiting_review.length > 0 && (
          <span className="text-[var(--color-muted)]">
            · awaiting review: {status.conflicts_awaiting_review.map((c) => `conflict ${c}`).join(", ")}
          </span>
        )}
      </div>
      {data.human_reviews.length > 0 ? (
        <ul className="mt-2 space-y-2">
          {data.human_reviews.map((r) => (
            <li
              key={r.id}
              className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={r.decision === "approved" ? "success" : r.decision === "rejected" ? "danger" : "warning"}>
                  {titleCase(r.decision)}
                </Badge>
                <span className="text-[var(--color-ink)]">{r.reviewer}</span>
                <span className="text-xs text-[var(--color-faint)]">
                  conclusion {r.conclusion_id} · {formatDate(r.created_at)}
                </span>
              </div>
              {r.note && <p className="mt-1 text-[var(--color-muted)]">{r.note}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          No human review decisions have been recorded yet.
        </p>
      )}
    </ReportSectionCard>
  );
}

// ------------------------------------------------------------------ activity
function ActivitySection({ data }: { data: ReportData }) {
  const [open, setOpen] = useState(false);
  const activity = data.agent_activity;
  return (
    <ReportSectionCard
      title="Agent Activity Summary"
      subtitle={`${activity.count} agent action(s) recorded across ${activity.by_agent.length} agent(s).`}
    >
      <ul className="space-y-1.5">
        {activity.by_agent.map((a) => (
          <li
            key={a.agent_name}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] p-2.5 text-sm"
          >
            <span className="text-[var(--color-ink)]">{a.agent_name}</span>
            <span className="text-xs text-[var(--color-faint)]">
              {a.actions} action(s) · {a.successes} success · {a.failures} failed ·{" "}
              {a.total_duration_ms} ms
            </span>
          </li>
        ))}
      </ul>
      {activity.timeline.length > 0 && (
        <>
          <button
            onClick={() => setOpen((v) => !v)}
            className="text-xs text-[var(--color-primary-soft)] hover:underline print:hidden"
          >
            {open ? "Hide" : "Show"} full activity timeline ({activity.timeline.length})
          </button>
          {open && (
            <ul className="max-h-72 space-y-1 overflow-auto font-mono text-[11px] text-[var(--color-muted)]">
              {activity.timeline.map((t) => (
                <li key={t.id} className="border-b border-[var(--color-border-soft)]/50 py-1">
                  <span className="text-[var(--color-faint)]">#{t.sequence}</span>{" "}
                  <span className="text-[var(--color-ink)]">{t.agent_name}</span> · {t.action} ·{" "}
                  <span
                    className={
                      t.status === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-success)]"
                    }
                  >
                    {t.status}
                  </span>{" "}
                  · {t.duration_ms} ms
                  {t.error && <span className="text-[var(--color-danger)]"> · {t.error}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </ReportSectionCard>
  );
}

// ----------------------------------------------------- limitations/timestamps
function LimitationsSection({ data }: { data: ReportData }) {
  const t = data.timestamps;
  const rows: [string, string][] = [
    ["Created", formatDate(t.created_at as string)],
    ["Started", formatDate(t.started_at as string)],
    ["Completed", formatDate(t.completed_at as string)],
    ["Report generated", formatDate(t.generated_at as string)],
    [
      "Duration",
      t.duration_seconds != null ? `${t.duration_seconds} second(s)` : "not recorded",
    ],
  ];
  return (
    <ReportSectionCard
      title="Limitations and Timestamps"
      subtitle="All times are UTC. Confidence is a bounded support indicator, not a probability."
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm md:grid-cols-3">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt className="text-xs uppercase tracking-wide text-[var(--color-faint)]">{k}</dt>
            <dd className="text-[var(--color-muted)]">{v}</dd>
          </div>
        ))}
      </dl>
      {data.limitations.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-sm text-[var(--color-muted)]">
          {data.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}

// --------------------------------------------------------------- audit trail
function AuditSection({ data }: { data: ReportData }) {
  return (
    <ReportSectionCard
      title="Audit Trail"
      subtitle="Every recorded change to the blackboard for this investigation, most recent first."
    >
      {data.audit_trail.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)]">No audit entries were recorded.</p>
      ) : (
        <ul className="space-y-1">
          {[...data.audit_trail].reverse().map((a) => (
            <li key={a.id} className="text-xs text-[var(--color-muted)]">
              <span className="text-[var(--color-faint)]">{formatDate(a.created_at)}</span> ·{" "}
              <Badge tone="neutral">
                {a.entity_type} {a.entity_id}
              </Badge>{" "}
              <span className="text-[var(--color-ink)]">{a.action}</span> by {a.actor}
              {a.summary ? `: ${a.summary}` : ""}
            </li>
          ))}
        </ul>
      )}
    </ReportSectionCard>
  );
}
