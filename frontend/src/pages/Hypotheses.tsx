import { useState } from "react";
import { Link } from "react-router-dom";
import { Lightbulb, ShieldCheck, Flag } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  ProgressBar,
  SectionHeader,
} from "../components/ui";
import { Badge, HypothesisStatusBadge } from "../components/badges";
import { percent, titleCase } from "../lib/format";

const STATUSES = [
  "",
  "proposed",
  "supported",
  "contradicted",
  "inconclusive",
  "review_required",
  "human_reviewed",
];

export default function Hypotheses() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, loading, error, refetch } = useApi(
    () => api.listHypotheses({ status, page }),
    [status, page]
  );

  const review = async (id: number, action: string) => {
    try {
      await api.reviewHypothesis(id, action);
      toast.success(
        action === "human_review"
          ? "Recorded as human-reviewed."
          : "Flagged for further investigation."
      );
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    }
  };

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;
  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Hypotheses"
        subtitle="Competing explanations for each conflict, scored by transparent evidence weighting."
        action={
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? titleCase(s) : "All statuses"}
              </option>
            ))}
          </select>
        }
      />

      {items.length === 0 ? (
        <EmptyState
          icon={<Lightbulb size={22} />}
          title="No hypotheses"
          description="Hypotheses are generated automatically during an investigation."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((h) => (
            <Card key={h.id} className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-[var(--color-ink)]">{h.title}</p>
                  <Link
                    to={`/conflicts/${h.conflict_id}`}
                    className="text-[11px] text-[var(--color-faint)] hover:text-[var(--color-primary-soft)]"
                  >
                    Conflict #C{h.conflict_id}
                  </Link>
                </div>
                <HypothesisStatusBadge status={h.status} />
              </div>

              {h.explanation && (
                <p className="text-xs text-[var(--color-muted)]">{h.explanation}</p>
              )}

              <div>
                <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--color-faint)]">
                  <span>Support score</span>
                  <span>{percent(h.support_score)}</span>
                </div>
                <ProgressBar
                  value={h.support_score}
                  tone={
                    h.status === "supported"
                      ? "success"
                      : h.status === "contradicted"
                      ? "danger"
                      : "primary"
                  }
                />
              </div>

              <div className="flex flex-wrap gap-2 text-[11px]">
                <Badge tone="success">{h.supporting_evidence_ids.length} supporting</Badge>
                <Badge tone="danger">{h.contradicting_evidence_ids.length} contradicting</Badge>
                {h.assumptions.length > 0 && (
                  <Badge tone="neutral">{h.assumptions.length} assumption(s)</Badge>
                )}
                {h.missing_information.length > 0 && (
                  <Badge tone="warning">{h.missing_information.length} gap(s)</Badge>
                )}
              </div>

              {h.missing_information.length > 0 && (
                <div className="rounded-lg bg-[var(--color-bg-soft)] p-2.5">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">
                    Missing information
                  </p>
                  <ul className="mt-1 list-inside list-disc text-[11px] text-[var(--color-muted)]">
                    {h.missing_information.map((m, i) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-auto flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => review(h.id, "flag_for_investigation")}
                >
                  <Flag size={13} /> Flag
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => review(h.id, "human_review")}
                >
                  <ShieldCheck size={13} /> Mark human-reviewed
                </Button>
              </div>
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
