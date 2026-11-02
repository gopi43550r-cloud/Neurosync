import { Cpu, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { Button, Card, ErrorState, Loading, SectionHeader } from "../components/ui";
import { AgentStateBadge } from "../components/badges";

function ContractRow({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="text-[11px] text-[var(--color-muted)]">
      <span className="font-medium text-[var(--color-faint)]">{label}: </span>
      {items.join("; ")}
    </div>
  );
}

export default function Agents() {
  const { data, loading, error, refetch } = useApi(() => api.agents(), [], {
    pollMs: 4000,
  });

  if (loading && !data) return <Loading label="Loading agents…" />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;

  const agents = data ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Agent monitor"
        subtitle="Six specialized reasoning agents contributing to the shared blackboard."
        action={
          <Button variant="outline" size="sm" onClick={refetch}>
            <RefreshCw size={14} /> Refresh
          </Button>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {agents.map((a) => (
          <Card key={a.name} className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-surface-2)] text-[var(--color-primary-soft)]">
                  <Cpu size={16} />
                </div>
                <div>
                  <p className="text-sm font-semibold">{a.name}</p>
                  <p className="text-[11px] text-[var(--color-faint)]">
                    {a.tasks_completed} task(s) completed
                  </p>
                </div>
              </div>
              <AgentStateBadge status={a.status} />
            </div>
            <p className="text-xs leading-relaxed text-[var(--color-muted)]">
              {a.responsibility}
            </p>

            <div className="space-y-2 rounded-lg border border-[var(--color-border)] p-3">
              <p className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">
                Contract
              </p>
              <ContractRow label="Requires" items={a.required_inputs} />
              <ContractRow label="Produces" items={a.expected_outputs} />
              <details className="text-[11px] text-[var(--color-muted)]">
                <summary className="cursor-pointer text-[10px] uppercase tracking-wide text-[var(--color-faint)]">
                  Run / stop conditions
                </summary>
                <div className="mt-2 space-y-2">
                  <ContractRow label="Runs when" items={a.run_conditions} />
                  <ContractRow label="Stops when" items={a.stop_conditions} />
                </div>
              </details>
            </div>

            <div className="mt-auto rounded-lg bg-[var(--color-bg-soft)] p-3">
              <p className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">
                Last result
              </p>
              <p className="mt-1 text-xs text-[var(--color-muted)]">
                {a.recent_result || a.last_action || "No activity yet."}
              </p>
              {a.last_duration_ms > 0 && (
                <p className="mt-1 text-[10px] text-[var(--color-faint)]">
                  took {a.last_duration_ms} ms
                </p>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
