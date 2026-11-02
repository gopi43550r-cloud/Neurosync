import { useState } from "react";
import { Link } from "react-router-dom";
import { ScrollText } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
} from "../components/ui";
import { Badge } from "../components/badges";
import { formatDate, titleCase } from "../lib/format";

const ENTITY_TYPES = [
  "",
  "claim",
  "evidence",
  "hypothesis",
  "conflict",
  "conclusion",
  "human_review",
];

export default function Audit() {
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(1);
  const { data, loading, error, refetch } = useApi(
    () => api.listAudit({ page, entity_type: entityType || undefined }),
    [entityType, page]
  );

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Audit Trail"
        subtitle="Timestamped, attributed history of every change to the blackboard"
        action={
          <select
            value={entityType}
            onChange={(e) => {
              setEntityType(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-ink)] outline-none"
          >
            {ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t ? titleCase(t) : "All entities"}
              </option>
            ))}
          </select>
        }
      />

      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : (
        <Card>
          {!data || data.items.length === 0 ? (
            <EmptyState
              icon={<ScrollText size={22} />}
              title="No audit entries"
              description="Run an investigation to populate the audit trail."
            />
          ) : (
            <ul className="divide-y divide-[var(--color-border-soft)]">
              {data.items.map((e) => (
                <li key={e.id} className="flex flex-col gap-1 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="primary">{titleCase(e.entity_type)}</Badge>
                    <Badge tone="neutral">{titleCase(e.action)}</Badge>
                    {e.entity_id !== null && (
                      <span className="text-xs text-[var(--color-faint)]">
                        #{e.entity_id}
                      </span>
                    )}
                    <span
                      className={
                        e.actor === "agent"
                          ? "text-xs text-[var(--color-faint)]"
                          : "text-xs text-[var(--color-violet)]"
                      }
                    >
                      by {e.actor}
                    </span>
                    <span className="ml-auto text-xs text-[var(--color-faint)]">
                      {formatDate(e.created_at)}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--color-ink)]">{e.summary}</p>
                  <div className="flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
                    {e.conflict_id !== null && (
                      <Link
                        to={`/conflicts/${e.conflict_id}`}
                        className="hover:text-[var(--color-primary-soft)]"
                      >
                        conflict #{e.conflict_id}
                      </Link>
                    )}
                    {e.investigation_id !== null && (
                      <Link
                        to={`/investigations/${e.investigation_id}`}
                        className="hover:text-[var(--color-primary-soft)]"
                      >
                        investigation #{e.investigation_id}
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
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
