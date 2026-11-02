import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Play, Plus, Radar } from "lucide-react";
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
  SectionHeader,
} from "../components/ui";
import { Badge, InvestigationStatusBadge } from "../components/badges";
import { cn, relativeTime, titleCase } from "../lib/format";

const STATUSES = ["", "created", "running", "completed", "cancelled", "error"];

export default function Investigations() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [page, setPage] = useState(1);
  const list = useApi(
    () => api.listInvestigations({ page, status: status || undefined }),
    [page, status],
    { pollMs: 6000 }
  );
  const docs = useApi(() => api.listDocuments({ page_size: 200 }), []);
  const conflicts = useApi(() => api.listConflicts({ page_size: 200 }), []);

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [question, setQuestion] = useState("");
  const [docIds, setDocIds] = useState<number[]>([]);
  const [confIds, setConfIds] = useState<number[]>([]);
  const [iterationLimit, setIterationLimit] = useState(25);
  const [minEvidence, setMinEvidence] = useState(1);

  const toggle = (list: number[], id: number, set: (v: number[]) => void) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  const submit = async () => {
    if (!name.trim()) {
      toast.error("Give the investigation a name.");
      return;
    }
    if (!docIds.length && !confIds.length) {
      toast.error("Select at least one document or conflict.");
      return;
    }
    try {
      const inv = await api.createInvestigation({
        name: name.trim(),
        research_question: question,
        document_ids: docIds,
        conflict_ids: confIds,
        iteration_limit: iterationLimit,
        min_evidence_threshold: minEvidence,
      });
      await api.investigationAction(inv.id, "start");
      toast.success("Investigation started.");
      navigate(`/investigations/${inv.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create investigation");
    }
  };

  const items = list.data?.items ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Investigations"
        subtitle="Task the agent collective with resolving conflicts and open questions."
        action={
          <div className="flex items-center gap-2">
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
            <Button size="sm" onClick={() => setCreating((v) => !v)}>
              <Plus size={14} /> {creating ? "Cancel" : "New investigation"}
            </Button>
          </div>
        }
      />

      {creating && (
        <Card className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Resolve equipment temperature conflict"
                className="input"
              />
            </Field>
            <Field label="Iteration limit">
              <input
                type="number"
                min={1}
                max={200}
                value={iterationLimit}
                onChange={(e) => setIterationLimit(Number(e.target.value))}
                className="input"
              />
            </Field>
          </div>
          <Field label="Research question (optional)">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="What should the agents determine?"
              className="input resize-none"
            />
          </Field>
          <Field label={`Documents (${docIds.length})`}>
            <div className="flex flex-wrap gap-2">
              {(docs.data?.items ?? []).map((d) => (
                <Chip
                  key={d.id}
                  active={docIds.includes(d.id)}
                  onClick={() => toggle(docIds, d.id, setDocIds)}
                >
                  {d.filename}
                </Chip>
              ))}
              {(docs.data?.items.length ?? 0) === 0 && (
                <span className="text-xs text-[var(--color-faint)]">No documents available.</span>
              )}
            </div>
          </Field>
          <Field label={`Conflicts (${confIds.length})`}>
            <div className="flex flex-wrap gap-2">
              {(conflicts.data?.items ?? []).map((c) => (
                <Chip
                  key={c.id}
                  active={confIds.includes(c.id)}
                  onClick={() => toggle(confIds, c.id, setConfIds)}
                >
                  C{c.id} · {c.severity}
                </Chip>
              ))}
              {(conflicts.data?.items.length ?? 0) === 0 && (
                <span className="text-xs text-[var(--color-faint)]">
                  No conflicts yet — upload documents first.
                </span>
              )}
            </div>
          </Field>
          <Field label="Minimum evidence threshold">
            <input
              type="number"
              min={0}
              max={50}
              value={minEvidence}
              onChange={(e) => setMinEvidence(Number(e.target.value))}
              className="input w-32"
            />
          </Field>
          <div className="flex justify-end">
            <Button onClick={submit}>
              <Play size={14} /> Create &amp; start
            </Button>
          </div>
        </Card>
      )}

      {list.loading && !list.data ? (
        <Loading />
      ) : list.error && !list.data ? (
        <ErrorState message={list.error} onRetry={list.refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Radar size={22} />}
          title="No investigations"
          description="Create one, or load the demo scenario from Overview."
        />
      ) : (
        <div className="space-y-3">
          {items.map((inv) => (
            <Link key={inv.id} to={`/investigations/${inv.id}`}>
              <Card className="flex items-center gap-4 transition hover:border-[var(--color-primary)]/50">
                <div className="flex-1">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <InvestigationStatusBadge status={inv.status} />
                    {inv.is_demo && <Badge tone="info">demo</Badge>}
                    <span className="text-sm font-medium">{inv.name}</span>
                  </div>
                  {inv.research_question && (
                    <p className="line-clamp-1 text-xs text-[var(--color-muted)]">
                      {inv.research_question}
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
                    <span>{inv.iteration_count} iterations</span>
                    <span>{inv.document_count} docs</span>
                    <span>{inv.conflict_count} conflicts</span>
                    <span>{inv.evidence_count} evidence</span>
                    <span>{inv.conclusion_count} conclusions</span>
                    {inv.stop_reason && <span>stop: {titleCase(inv.stop_reason)}</span>}
                    <span>{relativeTime(inv.updated_at)}</span>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {list.data && (
        <Pagination
          page={list.data.page}
          pageSize={list.data.page_size}
          total={list.data.total}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[var(--color-faint)]">
        {label}
      </span>
      {children}
    </label>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition",
        active
          ? "border-[var(--color-primary)] bg-[var(--color-primary)]/20 text-[var(--color-ink)]"
          : "border-[var(--color-border)] text-[var(--color-muted)] hover:border-[var(--color-primary)]/50"
      )}
    >
      {children}
    </button>
  );
}
