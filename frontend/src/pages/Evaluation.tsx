import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  CheckCircle2,
  Download,
  FlaskConical,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Upload,
  XCircle,
} from "lucide-react";
import { api } from "../api/client";
import type {
  AgentPerformanceOut,
  EvaluationDatasetOut,
  EvaluationRunOut,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge } from "../components/badges";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  SectionHeader,
  Stat,
} from "../components/ui";
import { formatDate, relativeTime, titleCase } from "../lib/format";

const CHART_COLORS = ["#818cf8", "#22d3ee", "#34d399", "#fbbf24", "#f87171", "#a855f7"];

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function rate(value: unknown): string {
  const v = num(value);
  return v == null ? "n/a" : `${(v * 100).toFixed(1)}%`;
}

function duration(value: number | null | undefined): string {
  if (value == null) return "n/a";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function count(run: EvaluationRunOut | null, key: string): number {
  const counts = run?.metrics?.overall?.counts;
  return typeof counts?.[key] === "number" ? counts[key] : 0;
}

function overall(run: EvaluationRunOut | null): Record<string, any> {
  return run?.metrics?.overall ?? {};
}

function provenanceBadge(provenance: string) {
  if (provenance === "reference_labelled")
    return <Badge tone="violet">Reference benchmark</Badge>;
  return <Badge tone="info">User-labelled</Badge>;
}

function statusBadge(status: string) {
  if (status === "completed") return <Badge tone="success">Completed</Badge>;
  if (status === "failed") return <Badge tone="danger">Failed</Badge>;
  return <Badge tone="warning">{titleCase(status)}</Badge>;
}

function expectedText(run: EvaluationRunOut, expected: Record<string, any>): string {
  if (run.kind === "conflict_detection") {
    return expected.label ? "Contradiction" : "No contradiction";
  }
  return titleCase(String(expected.verdict ?? "unknown"));
}

function predictedText(run: EvaluationRunOut, predicted: Record<string, any>): string {
  if (run.kind === "conflict_detection") {
    return predicted.predicted_confirmed ? "Contradiction" : "No contradiction";
  }
  return titleCase(String(predicted.verdict ?? predicted.predicted_verdict ?? "unknown"));
}

export default function Evaluation() {
  const toast = useToast();
  const dashboard = useApi(() => api.evaluationDashboard(), []);
  const [runsVersion, setRunsVersion] = useState(0);
  const runs = useApi(() => api.evaluationRuns({ limit: 30 }), [runsVersion]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const runDetail = useApi(
    () => (selectedRunId != null ? api.evaluationRun(selectedRunId) : Promise.resolve(null)),
    [selectedRunId],
    { enabled: selectedRunId != null }
  );
  const [selectedDatasetId, setSelectedDatasetId] = useState<number | null>(null);
  const datasetDetail = useApi(
    () => (selectedDatasetId != null ? api.evaluationDataset(selectedDatasetId) : Promise.resolve(null)),
    [selectedDatasetId, runsVersion],
    { enabled: selectedDatasetId != null }
  );
  const [runningId, setRunningId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [jsonText, setJsonText] = useState(defaultTemplate());
  const [creating, setCreating] = useState(false);
  const [failuresOnly, setFailuresOnly] = useState(false);

  const refreshAll = () => {
    dashboard.refetch();
    runs.refetch();
  };

  const runDataset = async (id: number) => {
    setRunningId(id);
    try {
      const result = await api.runEvaluationDataset(id);
      toast.success(
        `Run ${result.id}: ${result.passed} passed, ${result.failed} failed of ${result.case_count} cases.`
      );
      setSelectedRunId(result.id);
      setRunsVersion((v) => v + 1);
      refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setRunningId(null);
    }
  };

  const deleteDataset = async (dataset: EvaluationDatasetOut) => {
    if (!window.confirm(`Delete the test set "${dataset.name}" and all its runs?`)) return;
    try {
      await api.deleteEvaluationDataset(dataset.id);
      toast.success("Test set deleted.");
      if (selectedDatasetId === dataset.id) setSelectedDatasetId(null);
      setRunsVersion((v) => v + 1);
      refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  const createDataset = async () => {
    setCreating(true);
    try {
      let payload: any;
      try {
        payload = JSON.parse(jsonText);
      } catch {
        throw new Error("The test-set definition is not valid JSON.");
      }
      const created = await api.createEvaluationDataset(payload);
      toast.success(`Created "${created.name}" with ${created.case_count} labelled cases.`);
      setSelectedDatasetId(created.id);
      setShowCreate(false);
      setJsonText(defaultTemplate());
      setRunsVersion((v) => v + 1);
      refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const uploadDataset = async (file: File | null) => {
    if (!file) return;
    try {
      const created = await api.uploadEvaluationDataset(file);
      toast.success(`Uploaded "${created.name}" with ${created.case_count} labelled cases.`);
      setSelectedDatasetId(created.id);
      setRunsVersion((v) => v + 1);
      refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  if (dashboard.loading && !dashboard.data) return <Loading label="Loading evaluation dashboard…" />;
  if (dashboard.error && !dashboard.data)
    return <ErrorState message={dashboard.error} onRetry={dashboard.refetch} />;
  if (!dashboard.data) return null;

  const data = dashboard.data;
  const conflict = data.conflict_detection;
  const evidence = data.evidence_verification;
  const selectedRun =
    selectedRunId != null
      ? runDetail.data
      : conflict ?? evidence ?? null;

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Evaluation & Performance"
        subtitle="Metrics computed from human-labelled test cases using the real extraction, conflict-detection and fact-verification code. Every score is traceable to persisted per-case outcomes."
        action={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={refreshAll}>
              <RefreshCw size={14} /> Refresh
            </Button>
            <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
              <Plus size={14} /> New test set
            </Button>
          </div>
        }
      />

      <div className="flex items-start gap-3 rounded-xl border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-4 text-sm">
        <ShieldCheck size={18} className="mt-0.5 shrink-0 text-[var(--color-warning)]" />
        <div className="space-y-1">
          <p className="font-medium text-[var(--color-ink)]">Ground truth, not self-assessment</p>
          <p className="text-[var(--color-muted)]">{data.disclaimer}</p>
          <p className="text-xs text-[var(--color-faint)]">{data.validation_note}</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Conflict precision"
          value={rate(overall(conflict).precision)}
          hint={`${count(conflict, "tp")} TP / ${count(conflict, "fp")} FP`}
          tone="primary"
        />
        <Stat
          label="Conflict recall"
          value={rate(overall(conflict).recall)}
          hint={`${count(conflict, "tp")} TP / ${count(conflict, "fn")} FN`}
          tone="primary"
        />
        <Stat
          label="Conflict F1"
          value={rate(overall(conflict).f1)}
          hint={`Accuracy ${rate(overall(conflict).accuracy)}`}
          tone="success"
        />
        <Stat
          label="Evidence accuracy"
          value={rate(overall(evidence).accuracy)}
          hint={`Macro F1 ${rate(overall(evidence).macro_f1)}`}
          tone="success"
        />
        <Stat
          label="Agent tasks completed"
          value={data.agents.completed_tasks}
          hint={`${data.agents.failed_tasks} failed · ${data.agents.total_tasks} total`}
        />
        <Stat
          label="Agent avg task time"
          value={duration(data.agents.avg_duration_ms)}
          hint="Real execution ledger, all agents"
        />
        <Stat
          label="Documents processed"
          value={data.documents.documents_processed}
          hint={`${data.documents.documents_total} uploaded · ${data.documents.documents_error} errors`}
        />
        <Stat
          label="Claims extracted"
          value={data.documents.claims_extracted}
          hint={`${data.documents.conflicts_detected} conflicts detected`}
        />
      </div>

      {showCreate && (
        <Card>
          <SectionHeader
            title="Add a labelled test set"
            subtitle="A test set needs human-authored expectations. Conflict cases expect a boolean label; evidence cases expect one of supported, contradicted, partially_supported or unverified."
          />
          <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
            <textarea
              value={jsonText}
              onChange={(event) => setJsonText(event.target.value)}
              spellCheck={false}
              className="h-72 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-soft)] p-3 font-mono text-xs text-[var(--color-ink)] outline-none focus:border-[var(--color-primary)]"
            />
            <div className="flex flex-col gap-2">
              <Button onClick={createDataset} disabled={creating}>
                <Plus size={14} /> {creating ? "Creating…" : "Create test set"}
              </Button>
              <label className="focus-ring inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-ink)] hover:border-[var(--color-primary-soft)]">
                <Upload size={14} /> Upload JSON
                <input
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  onChange={(event) => uploadDataset(event.target.files?.[0] ?? null)}
                />
              </label>
              <p className="text-xs text-[var(--color-faint)]">
                Upload accepts the same JSON shape shown in the editor.
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <SectionHeader
            title="Conflict detection benchmark"
            subtitle={
              conflict
                ? `${conflict.dataset_name} · ${conflict.case_count} labelled cases`
                : "Run the reference benchmark to populate this chart."
            }
            action={conflict ? <Badge tone="violet">Reference</Badge> : undefined}
          />
          {conflict ? (
            <>
              <MetricChart run={conflict} />
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[var(--color-muted)] sm:grid-cols-4">
                <MatrixCell label="True positive" value={count(conflict, "tp")} />
                <MatrixCell label="False positive" value={count(conflict, "fp")} />
                <MatrixCell label="False negative" value={count(conflict, "fn")} />
                <MatrixCell label="True negative" value={count(conflict, "tn")} />
              </div>
              <ConfusionMatrix run={conflict} />
            </>
          ) : (
            <EmptyState
              icon={<TriangleAlert size={22} />}
              title="No completed conflict run"
              description="Run the built-in conflict-detection benchmark below."
            />
          )}
        </Card>

        <Card>
          <SectionHeader
            title="Evidence verification benchmark"
            subtitle={
              evidence
                ? `${evidence.dataset_name} · ${evidence.case_count} labelled cases`
                : "Run the reference benchmark to populate this chart."
            }
            action={evidence ? <Badge tone="violet">Reference</Badge> : undefined}
          />
          {evidence ? (
            <>
              <MetricChart run={evidence} />
              <ConfusionMatrix run={evidence} />
            </>
          ) : (
            <EmptyState
              icon={<FlaskConical size={22} />}
              title="No completed evidence run"
              description="Run the built-in evidence-verification benchmark below."
            />
          )}
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <SectionHeader
            title="Agent performance"
            subtitle="Real execution ledger: completed, failed and skipped tasks with measured durations."
          />
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.agents.agents} margin={{ left: -18, right: 8, top: 8 }}>
                <CartesianGrid stroke="#202c4d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="name"
                  tick={{ fill: "#9aa7c7", fontSize: 10 }}
                  interval={0}
                  angle={-18}
                  textAnchor="end"
                  height={54}
                />
                <YAxis tick={{ fill: "#9aa7c7", fontSize: 10 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "#0f172e", border: "1px solid #202c4d" }}
                  formatter={(value: number) => [`${value} tasks`, "Total"]}
                />
                <Bar dataKey="total_tasks" name="Tasks" fill="#818cf8" radius={[4, 4, 0, 0]} />
                <Bar dataKey="failed_tasks" name="Failed" fill="#f87171" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[var(--color-faint)]">
                <tr>
                  <th className="pb-2 font-medium">Agent</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 text-right font-medium">Done</th>
                  <th className="pb-2 text-right font-medium">Failed</th>
                  <th className="pb-2 text-right font-medium">Avg</th>
                </tr>
              </thead>
              <tbody>
                {data.agents.agents.map((agent) => (
                  <AgentRow key={agent.name} agent={agent} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <SectionHeader
            title="Document processing"
            subtitle="Real upload, processing-time and extraction statistics."
          />
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.documents.documents_by_day} margin={{ left: -22, right: 8, top: 8 }}>
                <CartesianGrid stroke="#202c4d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#9aa7c7", fontSize: 9 }}
                  tickFormatter={(value: string) => value.slice(5)}
                />
                <YAxis tick={{ fill: "#9aa7c7", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#0f172e", border: "1px solid #202c4d" }} />
                <Bar dataKey="documents" name="Uploaded" fill="#22d3ee" radius={[4, 4, 0, 0]} />
                <Bar dataKey="processed" name="Processed" fill="#34d399" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-[var(--color-muted)] sm:grid-cols-3">
            <MatrixCell label="Avg processing" value={duration(data.documents.avg_processing_ms)} />
            <MatrixCell label="Max processing" value={duration(data.documents.max_processing_ms)} />
            <MatrixCell label="With claims" value={data.documents.documents_with_claims} />
            <MatrixCell label="Conflicts resolved" value={data.documents.conflicts_resolved} />
            <MatrixCell label="Hypotheses" value={data.documents.hypotheses_total} />
            <MatrixCell label="Investigations" value={data.documents.investigations_total} />
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Labelled test sets"
          subtitle="Built-in reference benchmarks plus your own uploaded or created test cases."
        />
        {dashboard.data.datasets.length === 0 ? (
          <EmptyState title="No test sets" description="Create or upload a labelled test set." />
        ) : (
          <div className="space-y-2">
            {data.datasets.map((dataset) => (
              <div
                key={dataset.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-soft)]/60 p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-[var(--color-ink)]">{dataset.name}</span>
                    {provenanceBadge(dataset.source === "reference" ? "reference_labelled" : "user_labelled")}
                    <Badge tone="neutral">{titleCase(dataset.kind)}</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--color-muted)]">
                    {dataset.case_count} labelled cases · {dataset.description || "No description"}
                  </p>
                  {dataset.latest_run && (
                    <p className="mt-1 text-xs text-[var(--color-faint)]">
                      Latest run #{dataset.latest_run.id}: {statusBadge(dataset.latest_run.status)}{" "}
                      {dataset.latest_run.passed}/{dataset.latest_run.case_count} passed ·{" "}
                      {relativeTime(dataset.latest_run.started_at)}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setSelectedDatasetId((current) => (current === dataset.id ? null : dataset.id))
                    }
                  >
                    {selectedDatasetId === dataset.id ? "Hide cases" : "View cases"}
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => runDataset(dataset.id)}
                    disabled={runningId === dataset.id}
                  >
                    <Play size={13} /> {runningId === dataset.id ? "Running…" : "Run"}
                  </Button>
                  {!dataset.is_builtin && (
                    <Button size="sm" variant="danger" onClick={() => deleteDataset(dataset)}>
                      Delete
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {selectedDatasetId != null && (
          <div className="mt-4 rounded-xl border border-[var(--color-border)] p-3">
            {datasetDetail.loading && !datasetDetail.data ? (
              <Loading label="Loading cases…" />
            ) : datasetDetail.error ? (
              <ErrorState message={datasetDetail.error} onRetry={datasetDetail.refetch} />
            ) : datasetDetail.data ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                    {datasetDetail.data.name} — labelled cases
                  </h3>
                  <span className="text-xs text-[var(--color-faint)]">
                    Version {datasetDetail.data.version}
                  </span>
                </div>
                {datasetDetail.data.cases.map((testCase) => (
                  <details
                    key={testCase.id}
                    className="rounded-lg border border-[var(--color-border-soft)] p-3 text-sm"
                  >
                    <summary className="cursor-pointer text-[var(--color-ink)]">
                      <span className="font-mono text-xs">{testCase.case_key}</span>
                      <span className="ml-2 text-xs text-[var(--color-faint)]">
                        {testCase.category}
                      </span>
                      <span className="ml-2 text-xs text-[var(--color-muted)]">
                        expected: {JSON.stringify(testCase.expected)}
                      </span>
                    </summary>
                    <div className="mt-2 space-y-1 text-xs text-[var(--color-muted)]">
                      {testCase.payload.text_a != null && (
                        <>
                          <p>
                            <span className="text-[var(--color-faint)]">A:</span>{" "}
                            {testCase.payload.text_a || "—"}
                          </p>
                          <p>
                            <span className="text-[var(--color-faint)]">B:</span>{" "}
                            {testCase.payload.text_b || "—"}
                          </p>
                        </>
                      )}
                      {testCase.payload.claim_text && (
                        <>
                          <p>
                            <span className="text-[var(--color-faint)]">Claim:</span>{" "}
                            {testCase.payload.claim_text}
                          </p>
                          {(testCase.payload.documents ?? []).map(
                            (document: Record<string, any>, index: number) => (
                              <p key={index}>
                                <span className="text-[var(--color-faint)]">
                                  {document.filename}:
                                </span>{" "}
                                {document.text}
                              </p>
                            )
                          )}
                        </>
                      )}
                      {testCase.rationale && (
                        <p className="text-[var(--color-faint)]">
                          Why this label: {testCase.rationale}
                        </p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </Card>

      <Card>
        <SectionHeader
          title="Run explorer"
          subtitle="Inspect any completed or failed run. Exports include dataset information, metrics, confusion data and every test result."
          action={
            selectedRun && selectedRun.status === "completed" ? (
              <div className="flex gap-2">
                <a
                  href={api.evaluationExportUrl(selectedRun.id, "csv")}
                  className="focus-ring inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-ink)] hover:border-[var(--color-primary-soft)]"
                >
                  <Download size={13} /> CSV
                </a>
                <a
                  href={api.evaluationExportUrl(selectedRun.id, "pdf")}
                  className="focus-ring inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-ink)] hover:border-[var(--color-primary-soft)]"
                >
                  <Download size={13} /> PDF
                </a>
              </div>
            ) : undefined
          }
        />
        {runs.loading && !runs.data ? (
          <Loading label="Loading runs…" />
        ) : runs.error ? (
          <ErrorState message={runs.error} onRetry={runs.refetch} />
        ) : (runs.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={<Activity size={22} />}
            title="No evaluation runs yet"
            description="Run a labelled test set above."
          />
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {runs.data!.map((run) => (
                <button
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  className={`rounded-full border px-3 py-1.5 text-xs transition ${
                    selectedRunId === run.id
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)]/20 text-[var(--color-ink)]"
                      : "border-[var(--color-border)] text-[var(--color-muted)] hover:border-[var(--color-primary)]/50"
                  }`}
                >
                  #{run.id} {titleCase(run.kind)}{" "}
                  <span className="text-[10px] text-[var(--color-faint)]">
                    {run.passed}/{run.case_count}
                  </span>
                </button>
              ))}
            </div>

            {selectedRunId != null && runDetail.loading && !runDetail.data ? (
              <div className="mt-4">
                <Loading label="Loading run…" />
              </div>
            ) : selectedRunId != null && runDetail.error ? (
              <div className="mt-4">
                <ErrorState message={runDetail.error} onRetry={runDetail.refetch} />
              </div>
            ) : selectedRun ? (
              <div className="mt-4 space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                    Run #{selectedRun.id} — {selectedRun.dataset_name}
                  </h3>
                  {statusBadge(selectedRun.status)}
                  {provenanceBadge(selectedRun.provenance)}
                  <span className="text-xs text-[var(--color-faint)]">
                    {formatDate(selectedRun.started_at)} · {duration(selectedRun.duration_ms)}
                  </span>
                </div>
                {selectedRun.error && (
                  <p className="rounded-lg border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 p-3 text-xs text-[var(--color-danger)]">
                    {selectedRun.error}
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Stat label="Cases" value={selectedRun.case_count} />
                  <Stat label="Passed" value={selectedRun.passed} tone="success" />
                  <Stat label="Failed" value={selectedRun.failed} tone={selectedRun.failed ? "danger" : "default"} />
                  <Stat
                    label="Accuracy"
                    value={rate(overall(selectedRun).accuracy)}
                    tone="primary"
                  />
                </div>
                <div className="grid gap-6 xl:grid-cols-2">
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wide text-[var(--color-faint)]">
                      Headline metrics
                    </p>
                    <MetricChart run={selectedRun} />
                  </div>
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wide text-[var(--color-faint)]">
                      Confusion matrix
                    </p>
                    <ConfusionMatrix run={selectedRun} />
                  </div>
                </div>

                {selectedRun.failures.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wide text-[var(--color-faint)]">
                      Recorded failures
                    </p>
                    <div className="space-y-2">
                      {selectedRun.failures.map((failure, index) => (
                        <div
                          key={`${failure.case_key ?? failure.id ?? index}`}
                          className="rounded-lg border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 p-3 text-xs"
                        >
                          <p className="font-medium text-[var(--color-ink)]">
                            {failure.case_key ?? failure.id}{" "}
                            {failure.failure_kind && (
                              <span className="text-[var(--color-danger)]">
                                · {titleCase(String(failure.failure_kind))}
                              </span>
                            )}
                          </p>
                          <p className="mt-1 text-[var(--color-muted)]">
                            {failure.explanation}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs uppercase tracking-wide text-[var(--color-faint)]">
                      Test results
                    </p>
                    <label className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
                      <input
                        type="checkbox"
                        checked={failuresOnly}
                        onChange={(event) => setFailuresOnly(event.target.checked)}
                      />
                      Failures only
                    </label>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-[var(--color-faint)]">
                        <tr>
                          <th className="pb-2 font-medium">Case</th>
                          <th className="pb-2 font-medium">Category</th>
                          <th className="pb-2 font-medium">Expected</th>
                          <th className="pb-2 font-medium">Predicted</th>
                          <th className="pb-2 font-medium">Result</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRun.results
                          .filter((result) => !failuresOnly || !result.passed)
                          .map((result) => (
                            <tr
                              key={result.id}
                              className="border-t border-[var(--color-border-soft)] align-top"
                            >
                              <td className="py-2 pr-3 font-mono text-[11px] text-[var(--color-ink)]">
                                {result.case_key}
                              </td>
                              <td className="py-2 pr-3 text-[var(--color-muted)]">
                                {result.category}
                              </td>
                              <td className="py-2 pr-3 text-[var(--color-muted)]">
                                {expectedText(selectedRun, result.expected)}
                              </td>
                              <td className="py-2 pr-3 text-[var(--color-muted)]">
                                {predictedText(selectedRun, result.predicted)}
                              </td>
                              <td className="py-2">
                                {result.passed ? (
                                  <span className="inline-flex items-center gap-1 text-[var(--color-success)]">
                                    <CheckCircle2 size={13} /> Passed
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-[var(--color-danger)]">
                                    <XCircle size={13} /> Failed
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : null}
          </>
        )}
      </Card>
    </div>
  );
}

function MatrixCell({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg bg-[var(--color-bg-soft)] p-2">
      <p className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">{label}</p>
      <p className="text-sm font-semibold tabular-nums text-[var(--color-ink)]">{value}</p>
    </div>
  );
}

function AgentRow({ agent }: { agent: AgentPerformanceOut }) {
  return (
    <tr className="border-t border-[var(--color-border-soft)]">
      <td className="py-2 pr-3 text-[var(--color-ink)]">{agent.name}</td>
      <td className="py-2 pr-3">
        <Badge tone={agent.status === "running" ? "info" : agent.status === "failed" ? "danger" : "neutral"}>
          {titleCase(agent.status)}
        </Badge>
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-[var(--color-muted)]">
        {agent.completed_tasks}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-[var(--color-muted)]">
        {agent.failed_tasks}
      </td>
      <td className="py-2 text-right tabular-nums text-[var(--color-muted)]">
        {duration(agent.avg_duration_ms)}
      </td>
    </tr>
  );
}

function MetricChart({ run }: { run: EvaluationRunOut }) {
  const metrics = overall(run);
  const data = useMemo(() => {
    if (run.kind === "conflict_detection") {
      return [
        { name: "Precision", value: num(metrics.precision) ?? 0 },
        { name: "Recall", value: num(metrics.recall) ?? 0 },
        { name: "F1", value: num(metrics.f1) ?? 0 },
        { name: "Accuracy", value: num(metrics.accuracy) ?? 0 },
      ];
    }
    return [
      { name: "Accuracy", value: num(metrics.accuracy) ?? 0 },
      { name: "Macro precision", value: num(metrics.macro_precision) ?? 0 },
      { name: "Macro recall", value: num(metrics.macro_recall) ?? 0 },
      { name: "Macro F1", value: num(metrics.macro_f1) ?? 0 },
    ];
  }, [run, metrics]);

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: -18, right: 8, top: 8 }}>
          <CartesianGrid stroke="#202c4d" strokeDasharray="3 3" />
          <XAxis dataKey="name" tick={{ fill: "#9aa7c7", fontSize: 10 }} interval={0} />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: "#9aa7c7", fontSize: 10 }}
            tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
          />
          <Tooltip
            contentStyle={{ background: "#0f172e", border: "1px solid #202c4d" }}
            formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, "Score"]}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ConfusionMatrix({ run }: { run: EvaluationRunOut }) {
  const metrics = overall(run);
  if (run.kind === "conflict_detection") {
    const counts = run.confusion ?? metrics.counts ?? {};
    return (
      <div className="mt-3 overflow-x-auto">
        <table className="w-full max-w-md text-left text-xs">
          <thead className="text-[var(--color-faint)]">
            <tr>
              <th className="pb-2 font-medium" />
              <th className="pb-2 font-medium">Predicted conflict</th>
              <th className="pb-2 font-medium">Predicted none</th>
            </tr>
          </thead>
          <tbody className="text-[var(--color-muted)]">
            <tr className="border-t border-[var(--color-border-soft)]">
              <th className="py-2 text-left font-medium text-[var(--color-ink)]">Label conflict</th>
              <td className="py-2 tabular-nums text-[var(--color-success)]">TP {counts.tp ?? 0}</td>
              <td className="py-2 tabular-nums text-[var(--color-danger)]">FN {counts.fn ?? 0}</td>
            </tr>
            <tr className="border-t border-[var(--color-border-soft)]">
              <th className="py-2 text-left font-medium text-[var(--color-ink)]">Label none</th>
              <td className="py-2 tabular-nums text-[var(--color-danger)]">FP {counts.fp ?? 0}</td>
              <td className="py-2 tabular-nums text-[var(--color-success)]">TN {counts.tn ?? 0}</td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  const labels: string[] =
    (metrics.labels as string[] | undefined) ?? Object.keys(run.confusion ?? {});
  const confusion = run.confusion ?? {};
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead className="text-[var(--color-faint)]">
          <tr>
            <th className="pb-2 font-medium">Expected ↓ / Predicted →</th>
            {labels.map((label) => (
              <th key={label} className="pb-2 font-medium">
                {titleCase(label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-[var(--color-muted)]">
          {labels.map((label) => (
            <tr key={label} className="border-t border-[var(--color-border-soft)]">
              <th className="py-2 pr-2 text-left font-medium text-[var(--color-ink)]">
                {titleCase(label)}
              </th>
              {labels.map((predicted) => {
                const value = confusion?.[label]?.[predicted] ?? 0;
                return (
                  <td
                    key={predicted}
                    className={`py-2 tabular-nums ${
                      label === predicted && value > 0
                        ? "text-[var(--color-success)]"
                        : value > 0
                          ? "text-[var(--color-danger)]"
                          : "text-[var(--color-faint)]"
                    }`}
                  >
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function defaultTemplate(): string {
  return JSON.stringify(
    {
      name: "My labelled test set",
      kind: "conflict_detection",
      description: "Human-labelled cases for this deployment.",
      version: "1.0.0",
      cases: [
        {
          case_key: "example-conflict",
          category: "units",
          text_a: "The temperature was 100°F at 10:00 AM.",
          text_b: "The temperature was 40°C at 10:00 AM.",
          expected: {
            label: true,
            expected_flagged: true,
            expected_types: ["numerical_disagreement"],
          },
          rationale: "100°F is 37.8°C, which differs from 40°C beyond tolerance.",
        },
      ],
    },
    null,
    2
  );
}
