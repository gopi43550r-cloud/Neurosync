import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  Ban,
  Gauge,
  Pause,
  Play,
  Radio,
  RefreshCw,
  ScrollText,
  Target,
} from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useInvestigationEvents } from "../hooks/useInvestigationEvents";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  ProgressBar,
  SectionHeader,
  Stat,
} from "../components/ui";
import { Badge, InvestigationStatusBadge } from "../components/badges";
import { InvestigationVerificationSummary } from "../components/ClaimVerification";
import { InvestigationCredibilitySummary } from "../components/SourceCredibility";
import { InvestigationChatPanel } from "../components/InvestigationChat";
import { cn, relativeTime, titleCase } from "../lib/format";
import type { InvestigationEvent } from "../api/types";

const RUNNING_STATES = new Set(["running", "paused"]);
const LIVE_STATES = new Set(["running"]);

export default function InvestigationWorkspace() {
  const { id } = useParams();
  const investigationId = Number(id);
  const toast = useToast();

  const inv = useApi(
    () => api.getInvestigation(investigationId),
    [investigationId],
    { pollMs: 2000 }
  );
  const activity = useApi(
    () => api.activity(investigationId),
    [investigationId],
    { pollMs: 2500 }
  );

  const { events, state: streamState, progress: streamProgress, reconnect } = useInvestigationEvents(
    investigationId,
    useCallback(() => {
      // Refresh authoritative data as the stream advances.
      activity.refetch();
      inv.refetch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
  );

  const status = inv.data?.status ?? "created";
  const liveStatus = streamProgress?.status ?? status;
  const isLive = LIVE_STATES.has(liveStatus);
  const isRunning = liveStatus === "running";
  const currentAgent = isRunning
    ? (streamProgress?.current_agent || inv.data?.current_agent || "")
    : "";

  const [busy, setBusy] = useState(false);

  const act = async (action: "start" | "pause" | "resume" | "cancel") => {
    setBusy(true);
    try {
      await api.investigationAction(investigationId, action);
      toast.success(`Investigation ${action === "cancel" ? "cancelled" : action + "ed"}.`);
      inv.refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    activity.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  if (inv.loading && !inv.data) return <Loading />;
  if (inv.error) return <ErrorState message={inv.error} onRetry={inv.refetch} />;
  const data = inv.data!;

  const acts = activity.data ?? [];
  const completedCount =
    streamProgress?.completed ?? acts.filter((a) => a.status === "success").length;
  const failedCount = streamProgress?.failed ?? acts.filter((a) => a.status === "failed").length;
  const progress =
    liveStatus === "running"
      ? (streamProgress?.iteration_limit
          ? (streamProgress.iteration_count ?? data.iteration_count) / streamProgress.iteration_limit
          : 0) || 0
      : data.iteration_limit
      ? data.iteration_count / data.iteration_limit
      : 0;
  const resolved = data.conflict_count - data.open_conflict_count;

  return (
    <div className="space-y-6">
      <Link
        to="/investigations"
        className="inline-flex items-center gap-2 text-sm text-[var(--color-muted)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft size={14} /> All investigations
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{data.name}</h1>
            <InvestigationStatusBadge status={liveStatus} />
            {data.is_demo && <Badge tone="info">demonstration</Badge>}
            <StreamBadge state={streamState} live={isLive} />
          </div>
          {data.research_question && (
            <p className="mt-1 max-w-2xl text-sm text-[var(--color-muted)]">
              {data.research_question}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {liveStatus === "created" && (
            <Button size="sm" onClick={() => act("start")} disabled={busy}>
              <Play size={14} /> Start
            </Button>
          )}
          {liveStatus === "running" && (
            <Button size="sm" variant="outline" onClick={() => act("pause")} disabled={busy}>
              <Pause size={14} /> Pause
            </Button>
          )}
          {liveStatus === "paused" && (
            <Button size="sm" onClick={() => act("resume")} disabled={busy}>
              <Play size={14} /> Resume
            </Button>
          )}
          {RUNNING_STATES.has(liveStatus) && (
            <Button size="sm" variant="danger" onClick={() => act("cancel")} disabled={busy}>
              <Ban size={14} /> Cancel
            </Button>
          )}
          {liveStatus === "completed" && (
            <Link to={`/reports?investigation=${data.id}`}>
              <Button size="sm" variant="outline">
                <ScrollText size={14} /> View report
              </Button>
            </Link>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Stat
          label="Iterations"
          value={`${streamProgress?.iteration_count ?? data.iteration_count}/${data.iteration_limit}`}
        />
        <Stat label="Completed" value={completedCount} tone="success" hint="executions" />
        <Stat
          label="Failed"
          value={failedCount}
          tone={failedCount > 0 ? "danger" : "success"}
          hint="executions"
        />
        <Stat
          label="Conflicts"
          value={`${resolved}/${data.conflict_count}`}
          hint="resolved"
          tone="primary"
        />
        <Stat label="Evidence" value={data.evidence_count} />
        <Stat label="Conclusions" value={data.conclusion_count} tone="default" />
      </div>

      <InvestigationVerificationSummary investigationId={data.id} />

      <InvestigationCredibilitySummary investigationId={data.id} />

      <InvestigationChatPanel investigationId={data.id} />

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target size={15} className="text-[var(--color-primary-soft)]" />
            <span className="text-sm font-medium">
              {isRunning
                ? currentAgent || "Selecting next agent…"
                : liveStatus === "paused"
                ? "Investigation paused"
                : liveStatus === "completed"
                ? "Investigation completed"
                : liveStatus === "cancelled"
                ? "Investigation cancelled"
                : liveStatus === "error"
                ? "Investigation error"
                : "Awaiting agent selection"}
            </span>
          </div>
          {isRunning && currentAgent && (
            <span className="text-xs text-[var(--color-faint)]">
              priority {data.current_priority?.toFixed(1) ?? "0.0"} · info gain{" "}
              {data.current_info_gain?.toFixed(2) ?? "0.00"}
            </span>
          )}
        </div>
        <p className="mb-3 text-sm text-[var(--color-muted)]">
          {isRunning
            ? streamProgress?.current_objective || data.current_objective || "No active objective."
            : "No active objective."}
        </p>
        <ProgressBar value={progress} tone={isLive ? "primary" : "success"} />
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--color-faint)]">
          <span>Started {relativeTime(data.started_at)}</span>
          {data.completed_at && <span>Completed {relativeTime(data.completed_at)}</span>}
          {(streamProgress?.stop_reason || data.stop_reason) && (
            <Badge tone="neutral">
              stop: {titleCase(streamProgress?.stop_reason || data.stop_reason)}
            </Badge>
          )}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <SectionHeader
              title="Agent activity timeline"
              subtitle="Ordered decisions and their blackboard changes"
            />
            {acts.length > 0 && (
              <div className="mb-4 flex flex-wrap gap-2">
                <Badge tone="neutral">{acts.length} execution(s)</Badge>
                <Badge tone={acts.some((a) => a.attempt > 1) ? "warning" : "neutral"}>
                  {acts.filter((a) => a.attempt > 1).length} retry(ies)
                </Badge>
                <Badge tone={acts.some((a) => a.status === "failed") ? "danger" : "neutral"}>
                  {acts.filter((a) => a.status === "failed").length} failed
                </Badge>
              </div>
            )}
            {acts.length === 0 ? (
              <EmptyState
                icon={<Activity size={22} />}
                title="No activity yet"
                description="Start the investigation to watch the agents reason."
              />
            ) : (
              <ol className="relative space-y-3 pl-5">
                <span className="absolute left-[7px] top-2 bottom-2 w-px bg-[var(--color-border)]" />
                {[...acts].reverse().map((a) => (
                  <li key={a.id} className="relative">
                    <span
                      className={cn(
                        "absolute -left-5 top-1.5 h-3 w-3 rounded-full border-2 border-[var(--color-bg)]",
                        a.status === "success"
                          ? "bg-[var(--color-success)]"
                          : a.status === "failed"
                          ? "bg-[var(--color-danger)]"
                          : "bg-[var(--color-warning)]"
                      )}
                    />
                    <div className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[11px] font-mono text-[var(--color-faint)]">
                          #{a.sequence}
                        </span>
                        <span className="text-sm font-medium">{a.agent_name}</span>
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
                        {a.attempt > 1 && <Badge tone="warning">retry {a.attempt}</Badge>}
                        <span className="ml-auto text-[11px] text-[var(--color-faint)]">
                          {relativeTime(a.created_at)}
                          {a.duration_ms ? ` · ${a.duration_ms} ms` : ""}
                        </span>
                      </div>
                      <p className="mt-1.5 text-sm text-[var(--color-ink)]">
                        {a.output_summary || a.action}
                      </p>
                      {a.error && (
                        <p className="mt-1 text-xs text-[var(--color-danger)]">
                          <span className="text-[var(--color-faint)]">error: </span>
                          {a.error}
                        </p>
                      )}
                      {a.reason && (
                        <p className="mt-1 text-xs text-[var(--color-muted)]">
                          <span className="text-[var(--color-faint)]">why: </span>
                          {a.reason}
                        </p>
                      )}
                      {(a.input_record_ids?.length > 0 || a.output_record_ids?.length > 0) && (
                        <p className="mt-1 text-[11px] font-mono text-[var(--color-faint)]">
                          {a.input_record_ids?.length > 0 &&
                            `in [${a.input_record_ids.join(", ")}]`}
                          {a.input_record_ids?.length > 0 &&
                            a.output_record_ids?.length > 0 &&
                            " → "}
                          {a.output_record_ids?.length > 0 &&
                            `out [${a.output_record_ids.join(", ")}]`}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div>
          <Card className="sticky top-24">
            <SectionHeader
              title={streamState === "ended" ? "Recent events" : "Live event stream"}
              subtitle={
                streamState === "reconnecting"
                  ? "Reconnecting to the progress stream…"
                  : "Recent persisted events + server-sent updates"
              }
              action={
                streamState === "error" ? (
                  <Button size="sm" variant="outline" onClick={reconnect}>
                    <RefreshCw size={13} /> Reconnect
                  </Button>
                ) : undefined
              }
            />
            {events.length === 0 ? (
              <p className="py-8 text-center text-sm text-[var(--color-muted)]">
                {isLive
                  ? streamState === "reconnecting"
                    ? "Reconnecting…"
                    : "Waiting for events…"
                  : "No streamed events."}
              </p>
            ) : (
              <ul className="max-h-[520px] space-y-1.5 overflow-auto pr-1 font-mono text-[11px]">
                {[...events].reverse().map((e) => (
                  <EventRow key={e.id} event={e} />
                ))}
              </ul>
            )}
            {events.length > 0 && (
              <p className="mt-2 border-t border-[var(--color-border-soft)] pt-2 text-[10px] text-[var(--color-faint)]">
                {events.length} recent event(s) · live: {streamState}
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function StreamBadge({ state, live }: { state: string; live: boolean }) {
  const visible =
    live || state === "connecting" || state === "reconnecting" || state === "error";
  if (!visible) return null;
  const tone =
    state === "open"
      ? "success"
      : state === "reconnecting" || state === "connecting"
      ? "warning"
      : "danger";
  const label =
    state === "open"
      ? "live"
      : state === "reconnecting"
      ? "reconnecting"
      : state === "connecting"
      ? "connecting"
      : state === "error"
      ? "connection lost"
      : "ended";
  return (
    <Badge tone={tone} dot>
      <Radio size={11} /> {label}
    </Badge>
  );
}

function EventRow({ event }: { event: InvestigationEvent }) {
  const tone =
    event.event_type.includes("conflict")
      ? "text-[var(--color-danger)]"
      : event.event_type.includes("hypothesis")
      ? "text-[var(--color-warning)]"
      : event.event_type.includes("evidence")
      ? "text-[var(--color-success)]"
      : event.event_type.includes("conclusion")
      ? "text-[var(--color-violet)]"
      : "text-[var(--color-muted)]";
  const summary =
    (event.payload?.summary as string) ||
    (event.payload?.message as string) ||
    (event.payload?.agent as string) ||
    "";
  return (
    <li className="rounded border border-[var(--color-border-soft)] bg-[var(--color-bg-soft)] px-2 py-1.5">
      <div className="flex items-center gap-2">
        <span className={cn("truncate", tone)}>{event.event_type}</span>
        <span className="ml-auto shrink-0 text-[10px] text-[var(--color-faint)]">
          #{event.id}
        </span>
      </div>
      {summary && (
        <p className="mt-0.5 truncate text-[10px] text-[var(--color-faint)]">{summary}</p>
      )}
    </li>
  );
}
