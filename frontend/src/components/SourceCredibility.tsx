import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  FileSearch,
  HelpCircle,
  Info,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { api } from "../api/client";
import type {
  CredibilityConsistency,
  CredibilityFactor,
  SourceCredibilityOut,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge, CredibilityBadge } from "../components/badges";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
} from "../components/ui";
import { cn, titleCase } from "../lib/format";

const LEVELS = [
  "",
  "well_documented",
  "partially_documented",
  "limited_documentation",
  "unverifiable",
];

function factorTone(status: string) {
  if (status === "recorded" || status === "consistent") return "success" as const;
  if (status === "partial" || status === "mixed") return "warning" as const;
  if (status === "inconsistent") return "danger" as const;
  return "neutral" as const;
}

function RecordedValue({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">{label}</p>
      <p
        className={cn(
          "mt-0.5 text-sm",
          value ? "text-[var(--color-ink)]" : "italic text-[var(--color-faint)]"
        )}
      >
        {value || "Not recorded"}
      </p>
    </div>
  );
}

function FactorRow({ factor }: { factor: CredibilityFactor }) {
  const assessed = factor.score !== null;
  return (
    <details className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3">
      <summary className="cursor-pointer select-none">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-[var(--color-ink)]">{factor.label}</span>
          <Badge tone={factorTone(factor.status)}>{titleCase(factor.status)}</Badge>
          <span className="ml-auto text-xs tabular-nums text-[var(--color-muted)]">
            {assessed ? `${(factor.score! * 100).toFixed(0)}%` : "Not assessable"}
          </span>
        </div>
        <p className="mt-1 text-xs text-[var(--color-muted)]">{factor.summary}</p>
      </summary>
      <div className="mt-3 space-y-2 border-t border-[var(--color-border-soft)] pt-3 text-xs">
        <p className="text-[var(--color-muted)]">{factor.explanation}</p>
        {factor.inputs.length > 0 && (
          <div>
            <p className="font-medium text-[var(--color-ink)]">What was found</p>
            <ul className="mt-1 space-y-1 text-[var(--color-muted)]">
              {factor.inputs.map((item, index) => (
                <li key={index} className="flex gap-1.5">
                  <span className="text-[var(--color-success)]">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {factor.missing.length > 0 && (
          <div>
            <p className="font-medium text-[var(--color-ink)]">What is missing</p>
            <ul className="mt-1 space-y-1 text-[var(--color-muted)]">
              {factor.missing.map((item, index) => (
                <li key={index} className="flex gap-1.5">
                  <span className="text-[var(--color-warning)]">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

function ConsistencyDetail({ consistency }: { consistency: CredibilityConsistency }) {
  const examples = [...consistency.supporting, ...consistency.contradicting];
  if (examples.length === 0) return null;
  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <Badge tone="success">{consistency.supported} supported</Badge>
        <Badge tone="danger">{consistency.contradicted} contradicted</Badge>
        <Badge tone="warning">{consistency.partially_supported} partial</Badge>
        <Badge tone="neutral">{consistency.unverified} unverified</Badge>
      </div>
      <ul className="space-y-2">
        {examples.map((example, index) => (
          <li
            key={index}
            className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-2 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={example.relation === "supporting" ? "success" : "danger"}>
                {example.relation}
              </Badge>
              {example.other_document_id ? (
                <Link
                  to={`/documents/${example.other_document_id}`}
                  className="text-[var(--color-primary-soft)] hover:underline"
                >
                  {example.other_document_filename ?? `document #${example.other_document_id}`}
                </Link>
              ) : (
                <span className="text-[var(--color-faint)]">other source</span>
              )}
            </div>
            {example.claim_text && (
              <p className="mt-1 text-[var(--color-muted)]">
                <span className="text-[var(--color-faint)]">Source claim: </span>
                {example.claim_text}
              </p>
            )}
            {example.text && (
              <p className="mt-1 text-[var(--color-ink)]">“{example.text}”</p>
            )}
            {example.reason && (
              <p className="mt-1 text-[var(--color-faint)]">{example.reason}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Everything shown here is returned by the backend analyzer, which reads only
 * stored records. A factor with `score === null` is rendered as "not
 * assessable", never as zero.
 */
export function CredibilityBody({
  item,
  compact = false,
}: {
  item: SourceCredibilityOut;
  compact?: boolean;
}) {
  const factors = Object.values(item.factors);
  const assessed = factors.filter((factor) => factor.score !== null).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <CredibilityBadge level={item.overall_label} score={item.overall_score} />
        <Badge tone="neutral">
          {assessed}/{factors.length} factors assessable
        </Badge>
        <Badge tone="neutral">{(item.coverage * 100).toFixed(0)}% coverage</Badge>
        {item.is_demo && <Badge tone="info">demonstration data</Badge>}
      </div>

      <p className="text-sm text-[var(--color-muted)]">{item.summary}</p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <RecordedValue label="Author / creator" value={item.source_metadata.author} />
        <RecordedValue label="Organization" value={item.source_metadata.organization} />
        <RecordedValue label="Publication date" value={item.source_metadata.publication_date} />
        <RecordedValue label="Source type" value={item.source_metadata.source_type} />
      </div>

      {(item.source_metadata.identifiers.length > 0 ||
        item.source_metadata.version ||
        item.source_metadata.signature) && (
        <div className="flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
          {item.source_metadata.identifiers.length > 0 && (
            <span>identifiers: {item.source_metadata.identifiers.join(", ")}</span>
          )}
          {item.source_metadata.version && <span>version: {item.source_metadata.version}</span>}
          {item.source_metadata.signature && (
            <span>signature field: {item.source_metadata.signature}</span>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
        <span>{item.stored_file_present ? "stored file present" : "stored file missing"}</span>
        <span>checksum {item.checksum ? `${item.checksum.slice(0, 12)}…` : "not recorded"}</span>
        <span>{item.char_count} character(s) extracted</span>
        <span>{item.claim_count} claim(s)</span>
        <span>{item.evidence_count} evidence row(s)</span>
      </div>

      {item.warnings.length > 0 && (
        <div className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 p-2 text-xs text-[var(--color-warning)]">
          <p className="flex items-center gap-1.5 font-medium">
            <TriangleAlert size={13} /> Caveats for this source
          </p>
          <ul className="mt-1 space-y-1">
            {item.warnings.map((warning, index) => (
              <li key={index}>• {warning}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-2">
        {factors.map((factor) => (
          <FactorRow key={factor.key} factor={factor} />
        ))}
      </div>

      {!compact && <ConsistencyDetail consistency={item.consistency} />}

      {item.unknown_factors.length > 0 && (
        <p className="text-xs text-[var(--color-faint)]">
          Unknown and excluded from the aggregate (not scored as zero):{" "}
          {item.unknown_factors
            .map((key) => item.factors[key]?.label ?? key)
            .join(", ")}
          .
        </p>
      )}

      {!compact && (
        <details className="text-xs text-[var(--color-faint)]">
          <summary className="cursor-pointer select-none">
            How this indicator is calculated
          </summary>
          <p className="mt-2 text-[var(--color-muted)]">{item.methodology}</p>
          <p className="mt-1 text-[var(--color-muted)]">{item.explanation}</p>
          <p className="mt-1">{item.caveat}</p>
        </details>
      )}
    </div>
  );
}

/** Full assessment for one document (document detail page). */
export function SourceCredibilityPanel({ documentId }: { documentId: number }) {
  const { data, loading, error, refetch } = useApi(
    () => api.getDocumentCredibility(documentId),
    [documentId]
  );

  return (
    <Card>
      <SectionHeader
        title={
          <span className="inline-flex items-center gap-2">
            <ShieldCheck size={16} /> Source credibility
          </span>
        }
        subtitle="Six factors assessed from the records stored for this source."
        action={
          <Link to={`/documents?tab=credibility&document_id=${documentId}`}>
            <Button size="sm" variant="outline">
              All sources <ArrowUpRight size={13} />
            </Button>
          </Link>
        }
      />
      {loading && !data ? (
        <p className="py-4 text-sm text-[var(--color-muted)]">Assessing source…</p>
      ) : error && !data ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : data ? (
        <CredibilityBody item={data} />
      ) : null}
    </Card>
  );
}

function CredibilityCard({ item }: { item: SourceCredibilityOut }) {
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start gap-2">
        <FileSearch size={16} className="mt-0.5 shrink-0 text-[var(--color-primary-soft)]" />
        <div className="min-w-0 flex-1">
          <Link
            to={`/documents/${item.document_id}`}
            className="truncate font-medium hover:text-[var(--color-primary-soft)]"
          >
            {item.filename}
          </Link>
          <p className="text-[11px] text-[var(--color-faint)]">
            {item.file_type.toUpperCase()} · {item.claim_count} claim(s) ·{" "}
            {item.evidence_count} evidence row(s)
          </p>
        </div>
      </div>
      <CredibilityBody item={item} compact />
      <Link
        to={`/documents/${item.document_id}`}
        className="mt-auto inline-flex items-center gap-1 text-xs text-[var(--color-primary-soft)] hover:underline"
      >
        Open full assessment <ArrowUpRight size={12} />
      </Link>
    </Card>
  );
}

/** Filterable list of source assessments. */
export function SourceCredibilityListPanel({
  investigationId,
  documentId,
}: {
  investigationId?: number;
  documentId?: number;
}) {
  const [level, setLevel] = useState("");
  const [unknownOnly, setUnknownOnly] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const { data, loading, error, refetch } = useApi(
    () =>
      investigationId
        ? api.investigationSourceCredibility(investigationId, {
            page,
            page_size: 12,
            level: level || undefined,
            unknown_only: unknownOnly || undefined,
          })
        : api.listSourceCredibility({
            page,
            page_size: 12,
            q: q || undefined,
            level: level || undefined,
            unknown_only: unknownOnly || undefined,
            document_id: documentId,
          }),
    [investigationId, documentId, level, unknownOnly, q, page]
  );

  if (loading && !data) return <Loading label="Assessing sources…" />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;

  const items = data?.items ?? [];
  const counts = data?.counts;

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-3">
        <select
          value={level}
          onChange={(event) => {
            setLevel(event.target.value);
            setPage(1);
          }}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
        >
          {LEVELS.map((option) => (
            <option key={option} value={option}>
              {option ? titleCase(option) : "All credibility levels"}
            </option>
          ))}
        </select>
        <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-[var(--color-muted)]">
          <input
            type="checkbox"
            checked={unknownOnly}
            onChange={(event) => {
              setUnknownOnly(event.target.checked);
              setPage(1);
            }}
            className="h-3.5 w-3.5 accent-[var(--color-primary)]"
          />
          Unknown / unverifiable sources only
        </label>
        {!investigationId && (
          <div className="ml-auto flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
            <HelpCircle size={14} className="text-[var(--color-faint)]" />
            <input
              value={q}
              onChange={(event) => {
                setQ(event.target.value);
                setPage(1);
              }}
              placeholder="Search filename or metadata…"
              className="w-52 bg-transparent text-sm outline-none placeholder:text-[var(--color-faint)]"
            />
          </div>
        )}
      </Card>

      {counts && (
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge tone="success">{counts.well_documented} well documented</Badge>
          <Badge tone="info">{counts.partially_documented} partially documented</Badge>
          <Badge tone="warning">
            {counts.limited_documentation} limited documentation
          </Badge>
          <Badge tone="neutral">{counts.unverifiable} unverifiable</Badge>
          <Badge tone="neutral">{counts.unknown_author} without recorded author</Badge>
          <Badge tone="neutral">
            {counts.unknown_publication_date} without recorded publication date
          </Badge>
          <Badge tone="danger">
            {counts.with_consistency_conflicts} with cross-source conflicts
          </Badge>
        </div>
      )}

      {investigationId && data?.investigation_name && (
        <p className="text-xs text-[var(--color-faint)]">
          Scoped to investigation “{data.investigation_name}” (#{investigationId}).
        </p>
      )}

      {items.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={22} />}
          title="No sources match"
          description="Upload documents to assess their authenticity, provenance and consistency."
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((item) => (
            <CredibilityCard key={item.document_id} item={item} />
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

      {data && (
        <details className="text-xs text-[var(--color-faint)]">
          <summary className="flex cursor-pointer select-none items-center gap-1.5">
            <Info size={13} /> About this indicator
          </summary>
          <p className="mt-2 text-[var(--color-muted)]">{data.methodology}</p>
          <p className="mt-1">{data.caveat}</p>
        </details>
      )}
    </div>
  );
}

/** Compact credibility summary for the investigation workspace. */
export function InvestigationCredibilitySummary({
  investigationId,
}: {
  investigationId: number;
}) {
  const { data, loading, error } = useApi(
    () => api.investigationSourceCredibility(investigationId, { page_size: 1 }),
    [investigationId]
  );

  return (
    <Card>
      <SectionHeader
        title="Source credibility"
        subtitle="Authenticity, provenance and consistency of the investigation's sources."
        action={
          <Link to={`/documents?tab=credibility&investigation_id=${investigationId}`}>
            <Button size="sm" variant="outline">
              View sources <ArrowUpRight size={13} />
            </Button>
          </Link>
        }
      />
      {loading && !data ? (
        <p className="py-4 text-sm text-[var(--color-muted)]">Assessing sources…</p>
      ) : error && !data ? (
        <p className="text-sm text-[var(--color-danger)]">{error}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Badge tone="success">{data?.counts.well_documented ?? 0} well documented</Badge>
            <Badge tone="info">
              {data?.counts.partially_documented ?? 0} partially documented
            </Badge>
            <Badge tone="warning">
              {data?.counts.limited_documentation ?? 0} limited documentation
            </Badge>
            <Badge tone="neutral">{data?.counts.unverifiable ?? 0} unverifiable</Badge>
          </div>
          <p className="mt-2 text-xs text-[var(--color-faint)]">
            {data?.documents_considered ?? 0} source(s) assessed.{" "}
            {data?.counts.unknown_author ?? 0} lack a recorded author and{" "}
            {data?.counts.unknown_publication_date ?? 0} lack a recorded publication date.
            Unknown factors are excluded, never scored as zero.
          </p>
        </>
      )}
    </Card>
  );
}
