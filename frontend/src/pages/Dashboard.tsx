import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  Bot,
  FileText,
  FlaskConical,
  Lightbulb,
  Network,
  Play,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import { Button, Card, ErrorState, Loading, SectionHeader, Stat } from "../components/ui";
import { Badge, SeverityBadge } from "../components/badges";
import { relativeTime, titleCase } from "../lib/format";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f87171",
  medium: "#fbbf24",
  low: "#64719a",
};

export default function Dashboard() {
  const toast = useToast();
  const navigate = useNavigate();
  const [days, setDays] = useState(14);
  const { data, loading, error, refetch } = useApi(
    () => api.snapshot({ days }),
    [days],
    { pollMs: 5000 }
  );

  if (loading && !data) return <Loading label="Loading blackboard…" />;
  if (error && !data)
    return <ErrorState message={error} onRetry={refetch} />;

  const counts = data?.counts;
  const recent = data?.recent_activity ?? [];
  const sev = (data?.severity_distribution ?? []).map((s) => ({
    ...s,
    label: titleCase(s.severity),
  }));
  const timeline = (data?.activity_timeline ?? []).map((t) => ({
    ...t,
    label: new Date(t.date).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    }),
  }));

  const loadDemo = async () => {
    try {
      const res = await api.loadDemo(false);
      toast.success("Demonstration scenario loaded.");
      navigate(`/investigations/${res.investigation_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load demo");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            Live state of the blackboard: evidence, conflicts and agent activity.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={refetch}>
            <RefreshCw size={14} /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={loadDemo}>
            <Play size={14} /> Load demo
          </Button>
          <Button size="sm" onClick={() => navigate("/investigations")}>
            <Network size={14} /> New investigation
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Documents"
          value={counts?.documents ?? 0}
          hint={`${counts?.claims ?? 0} claims`}
        />
        <Stat
          label="Conflicts"
          value={counts?.conflicts ?? 0}
          hint={`${counts?.unresolved_conflicts ?? 0} open`}
          tone="danger"
        />
        <Stat
          label="Evidence"
          value={counts?.evidence ?? 0}
          hint={`${counts?.pending_verification ?? 0} unverified`}
        />
        <Stat
          label="Hypotheses"
          value={counts?.hypotheses ?? 0}
          hint={`${counts?.evidence_gaps ?? 0} gaps`}
          tone="warning"
        />
        <Stat
          label="Conclusions"
          value={counts?.conclusions ?? 0}
          hint={`${counts?.active_investigations ?? 0} active`}
          tone="success"
        />
        <Stat
          label="Human review"
          value={counts?.human_review_requests ?? 0}
          hint="flagged for people"
          tone="primary"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Conflict severity" subtitle="Distribution across the blackboard" />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sev} barCategoryGap="30%">
                <XAxis
                  dataKey="label"
                  stroke="#64719a"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="#64719a"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: "rgba(99,102,241,0.08)" }}
                  contentStyle={{
                    background: "#0f172e",
                    border: "1px solid #202c4d",
                    borderRadius: 12,
                    color: "#eef2ff",
                  }}
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {sev.map((entry) => (
                    <Cell
                      key={entry.severity}
                      fill={SEVERITY_COLORS[entry.severity] ?? "#6366f1"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <SectionHeader title="Agent activity" subtitle={`Blackboard events over the last ${days} days`} />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline}>
                <defs>
                  <linearGradient id="actFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="label"
                  stroke="#64719a"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  stroke="#64719a"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0f172e",
                    border: "1px solid #202c4d",
                    borderRadius: 12,
                    color: "#eef2ff",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#818cf8"
                  strokeWidth={2}
                  fill="url(#actFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DistributionCard
          title="Conflicts by category"
          items={data?.conflict_type_distribution ?? []}
          linkTo={(v) => `/conflicts?type=${encodeURIComponent(v)}`}
        />
        <DistributionCard
          title="Conflicts by status"
          items={data?.conflict_status_distribution ?? []}
          linkTo={(v) => `/conflicts?status=${encodeURIComponent(v)}`}
        />
        <DistributionCard
          title="Investigations by status"
          items={data?.investigation_status_distribution ?? []}
          linkTo={(v) => `/investigations?status=${encodeURIComponent(v)}`}
        />
        <DistributionCard
          title="Evidence by verification"
          items={data?.evidence_verification_distribution ?? []}
          linkTo={(v) => `/evidence?verification_status=${encodeURIComponent(v)}`}
        />
      </div>

      <Card>
        <SectionHeader
          title="Recent agent activity"
          subtitle="What the reasoning agents have done most recently"
        action={
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm outline-none"
              title="Activity window"
            >
              {[7, 14, 30, 90].map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
            <Button variant="ghost" size="sm" onClick={() => navigate("/agents")}>
              <Bot size={14} /> Agent monitor
            </Button>
          </div>
        }
        />
        {recent.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--color-muted)]">
            No agent activity yet. Load the demo scenario or upload documents, then
            start an investigation.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--color-border-soft)]">
            {recent.map((a) => (
              <li key={a.id} className="flex items-center gap-4 py-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--color-surface-2)] text-[var(--color-primary-soft)]">
                  {a.agent.includes("Conflict") ? (
                    <TriangleAlert size={15} />
                  ) : a.agent.includes("Evidence") ? (
                    <FileText size={15} />
                  ) : a.agent.includes("Hypothesis") ? (
                    <Lightbulb size={15} />
                  ) : a.agent.includes("Investigator") ? (
                    <FlaskConical size={15} />
                  ) : (
                    <Activity size={15} />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{a.agent}</p>
                  <p className="truncate text-xs text-[var(--color-muted)]">
                    {a.output_summary || a.action}
                  </p>
                </div>
                <Badge
                  tone={
                    a.status === "success"
                      ? "success"
                      : a.status === "failed"
                      ? "danger"
                      : "warning"
                  }
                >
                  {a.status}
                </Badge>
                <span className="w-20 shrink-0 text-right text-xs text-[var(--color-faint)]">
                  {relativeTime(a.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function DistributionCard({
  title,
  items,
  linkTo,
}: {
  title: string;
  items: { value: string; count: number }[];
  linkTo: (value: string) => string;
}) {
  const total = items.reduce((sum, i) => sum + i.count, 0);
  return (
    <Card className="flex flex-col">
      <SectionHeader title={title} subtitle={`${total} total`} />
      {items.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--color-muted)]">No data yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => {
            const pct = total > 0 ? (item.count / total) * 100 : 0;
            return (
              <li key={item.value}>
                <Link
                  to={linkTo(item.value)}
                  className="group block rounded-lg px-2 py-1.5 transition hover:bg-[var(--color-surface-2)]"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[var(--color-muted)] group-hover:text-[var(--color-ink)]">
                      {titleCase(item.value)}
                    </span>
                    <span className="text-[var(--color-faint)]">{item.count}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                    <div
                      className="h-full rounded-full bg-[var(--color-primary)]"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
