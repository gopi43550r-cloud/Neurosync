import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronRight, Filter, Search } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { Badge, ConflictStatusBadge, SeverityBadge } from "../components/badges";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
} from "../components/ui";
import { relativeTime, titleCase } from "../lib/format";

const SEVERITIES = ["", "critical", "high", "medium", "low"];
const STATUSES = ["", "open", "investigating", "resolved", "inconclusive", "human_review"];
const TYPES = [
  "",
  "direct_contradiction",
  "numerical_disagreement",
  "temporal_inconsistency",
  "source_disagreement",
  "missing_context",
  "semantic_inconsistency",
];

export default function Conflicts() {
  const [params] = useSearchParams();
  const [severity, setSeverity] = useState(params.get("severity") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [type, setType] = useState(params.get("type") ?? "");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(1);

  const update = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setPage(1);
  };

  const { data, loading, error, refetch } = useApi(
    () => api.listConflicts({ severity, status, conflict_type: type, q, page }),
    [severity, status, type, q, page]
  );

  const conflicts = data?.items ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Conflicts"
        subtitle="Contradictions detected across documents, each with a transparent reason."
      />

      <Card className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 text-[var(--color-faint)]">
          <Filter size={14} />
          <span className="text-xs uppercase tracking-wide">Filters</span>
        </div>
        <select
          value={severity}
          onChange={(e) => update(setSeverity)(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s ? titleCase(s) : "All severities"}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => update(setStatus)(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s ? titleCase(s) : "All statuses"}
            </option>
          ))}
        </select>
        <select
          value={type}
          onChange={(e) => update(setType)(e.target.value)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
        >
          {TYPES.map((s) => (
            <option key={s} value={s}>
              {s ? titleCase(s) : "All types"}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
          <Search size={14} className="text-[var(--color-faint)]" />
          <input
            value={q}
            onChange={(e) => update(setQ)(e.target.value)}
            placeholder="Search descriptions…"
            className="w-52 bg-transparent text-sm outline-none placeholder:text-[var(--color-faint)]"
          />
        </div>
      </Card>

      {loading && !data ? (
        <Loading />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : conflicts.length === 0 ? (
        <EmptyState
          title="No conflicts match"
          description="Try changing the filters, or load the demo scenario to see detections."
        />
      ) : (
        <div className="space-y-4">
          <div className="space-y-3">
            {conflicts.map((c) => (
            <Link key={c.id} to={`/conflicts/${c.id}`}>
              <Card className="group flex items-center gap-4 transition hover:border-[var(--color-primary)]/50">
                <div className="flex-1">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={c.severity} />
                    <ConflictStatusBadge status={c.status} />
                    <Badge tone="neutral">{titleCase(c.conflict_type)}</Badge>
                    <span className="text-xs text-[var(--color-faint)]">
                      #C{c.id} · {relativeTime(c.updated_at)}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--color-ink)]">{c.description}</p>
                  <p className="mt-1.5 text-xs text-[var(--color-faint)]">
                    {c.document_a ?? "?"} ↔ {c.document_b ?? "?"} ·{" "}
                    {c.evidence_count} evidence · {c.hypothesis_count} hypotheses ·{" "}
                    confidence {(c.confidence * 100).toFixed(0)}%
                  </p>
                </div>
                <ChevronRight
                  size={18}
                  className="shrink-0 text-[var(--color-faint)] transition group-hover:text-[var(--color-primary-soft)]"
                />
              </Card>
            </Link>
          ))}
          </div>
          <Pagination
            page={data?.page ?? page}
            pageSize={data?.page_size ?? 50}
            total={data?.total ?? 0}
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  );
}
