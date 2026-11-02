import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import { ExternalLink, RefreshCw, Workflow } from "lucide-react";
import { api } from "../api/client";
import type { BlackboardEventOut } from "../api/types";
import { useApi } from "../hooks/useApi";
import { Button, Card, ErrorState, Loading, SectionHeader, Spinner } from "../components/ui";
import { Badge } from "../components/badges";
import { relativeTime } from "../lib/format";

const COLUMN: Record<string, number> = {
  document: 0,
  claim: 1,
  conflict: 2,
  evidence: 3,
  hypothesis: 4,
  conclusion: 5,
};

const STYLES: Record<string, { border: string; bg: string; text: string }> = {
  document: { border: "#60a5fa", bg: "rgba(96,165,250,0.12)", text: "#93c5fd" },
  claim: { border: "#64719a", bg: "rgba(100,113,154,0.12)", text: "#cbd5e1" },
  conflict: { border: "#f87171", bg: "rgba(248,113,113,0.12)", text: "#fca5a5" },
  evidence: { border: "#34d399", bg: "rgba(52,211,153,0.12)", text: "#6ee7b7" },
  hypothesis: { border: "#fbbf24", bg: "rgba(251,191,36,0.12)", text: "#fcd34d" },
  conclusion: { border: "#a855f7", bg: "rgba(168,85,247,0.14)", text: "#d8b4fe" },
};

const EDGE_COLORS: Record<string, string> = {
  contradicts: "#f87171",
  supports: "#34d399",
  refutes: "#fb923c",
  extracted_from: "#334166",
  derived_from: "#334166",
  resolved_by: "#a855f7",
};

// Blackboard record id keys present on a graph node's data, in priority order.
const RAW_KEYS: [string, string][] = [
  ["conflict_id", "conflict"],
  ["evidence_id", "evidence"],
  ["hypothesis_id", "hypothesis"],
  ["conclusion_id", "conclusion"],
  ["claim_id", "claim"],
  ["document_id", "document"],
];

type Selected = { type: string; id: number; label: string };

function recordOf(raw: Record<string, unknown> | undefined): { type: string; id: number } | null {
  if (!raw) return null;
  for (const [key, type] of RAW_KEYS) {
    const value = raw[key];
    if (typeof value === "number") return { type, id: value };
  }
  return null;
}

function recordPath(type: string, id: number): string | null {
  if (type === "document") return `/documents/${id}`;
  if (type === "conflict") return `/conflicts/${id}`;
  return null;
}

function eventTone(type: string): "neutral" | "primary" | "success" | "warning" | "danger" | "info" | "violet" {
  if (type.includes("reevaluation")) return "primary";
  if (type.includes("conflict")) return "danger";
  if (type.includes("conclusion") || type.includes("human_review")) return "violet";
  if (type.includes("evidence")) return "success";
  if (type.includes("hypothesis")) return "warning";
  if (type.includes("claim") || type.includes("document")) return "info";
  return "neutral";
}

function EventRow({ event }: { event: BlackboardEventOut }) {
  return (
    <div className="flex flex-col gap-1 border-b border-[var(--color-border-soft)] py-2 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={eventTone(event.event_type)}>{event.event_type}</Badge>
        <span className="text-[11px] text-[var(--color-faint)]">{relativeTime(event.created_at)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--color-muted)]">
        <span>
          agent: <span className="text-[var(--color-ink)]">{event.agent_name ?? "—"}</span>
        </span>
        {event.entity_type && (
          <span>
            entity: <span className="text-[var(--color-ink)]">{event.entity_type} {event.entity_id}</span>
          </span>
        )}
        {event.related.length > 0 && (
          <span>
            related:{" "}
            <span className="text-[var(--color-ink)]">
              {event.related.map((r) => `${r.type} ${r.id}`).join(", ")}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}

function BBoardNode({ data }: NodeProps) {
  const type = (data.node_type as string) ?? "claim";
  const s = STYLES[type] ?? STYLES.claim;
  return (
    <div
      style={{
        borderColor: s.border,
        background: s.bg,
        color: "#eef2ff",
        borderRadius: 12,
        borderWidth: 1,
        borderStyle: "solid",
        padding: "8px 12px",
        width: 180,
        fontSize: 12,
        boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <p style={{ color: s.text, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {type}
      </p>
      <p style={{ marginTop: 2, lineHeight: 1.3 }}>{data.label as string}</p>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { bboard: BBoardNode };

export default function Blackboard() {
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useApi(
    () => api.snapshot(),
    [],
    { pollMs: 6000 }
  );

  const [selected, setSelected] = useState<Selected | null>(null);
  const [reevalBusy, setReevalBusy] = useState(false);
  const [reevalMessage, setReevalMessage] = useState<string | null>(null);

  const connected = useApi(
    () => api.blackboardConnected(selected!.type, selected!.id),
    [selected?.type, selected?.id],
    { enabled: !!selected }
  );
  const trace = useApi(
    () => api.blackboardTrace(selected!.type, selected!.id),
    [selected?.type, selected?.id],
    { enabled: !!selected }
  );

  const { nodes, edges } = useMemo(() => {
    const graph = data?.graph ?? { nodes: [], edges: [] };
    const gNodes = graph.nodes ?? [];
    const gEdges = graph.edges ?? [];

    const counters: Record<number, number> = {};
    const rfNodes: Node[] = gNodes.map((n) => {
      const col = COLUMN[n.node_type] ?? 3;
      counters[col] = (counters[col] ?? 0) + 1;
      const row = counters[col] - 1;
      return {
        id: n.id,
        type: "bboard",
        position: { x: col * 260, y: row * 96 },
        data: { label: n.label, node_type: n.node_type, raw: n.data },
      };
    });

    const rfEdges: Edge[] = gEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: e.edge_type === "contradicts" || e.edge_type === "supports",
      style: { stroke: EDGE_COLORS[e.edge_type] ?? "#334166" },
    }));

    return { nodes: rfNodes, edges: rfEdges };
  }, [data]);

  async function runReevaluation() {
    setReevalBusy(true);
    setReevalMessage(null);
    try {
      const summary = await api.reevaluate();
      setReevalMessage(
        `Processed ${summary.tasks} task(s): ${summary.genuine} genuine, ` +
          `${summary.reopened} reopened, ${summary.hypotheses_rescored} re-scored, ` +
          `${summary.conclusions_revised} conclusion(s) revised.`
      );
      refetch();
    } catch (e) {
      setReevalMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setReevalBusy(false);
    }
  }

  if (loading && !data) return <Loading label="Building blackboard graph…" />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;

  const counts = data?.counts;
  const recentEvents = data?.recent_events ?? [];
  const relationCounts = data?.relation_counts ?? {};
  const totalRelations = Object.values(relationCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Blackboard"
        subtitle="The shared knowledge store: documents, claims, conflicts, evidence, hypotheses and conclusions."
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={runReevaluation} disabled={reevalBusy}>
              {reevalBusy ? <Spinner /> : <Workflow size={14} />} Re-evaluate
            </Button>
            <Button variant="outline" size="sm" onClick={refetch}>
              <RefreshCw size={14} /> Refresh
            </Button>
          </div>
        }
      />

      {reevalMessage && (
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)]/50 px-4 py-2 text-xs text-[var(--color-muted)]">
          {reevalMessage}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        {[
          ["Documents", counts?.documents],
          ["Claims", counts?.claims],
          ["Conflicts", counts?.conflicts],
          ["Evidence", counts?.evidence],
          ["Hypotheses", counts?.hypotheses],
          ["Conclusions", counts?.conclusions],
          ["Relations", totalRelations],
        ].map(([label, value]) => (
          <Card key={label as string} className="flex items-center gap-3 px-4 py-2">
            <span className="text-xs uppercase tracking-wide text-[var(--color-faint)]">
              {label}
            </span>
            <span className="text-lg font-semibold tabular-nums">{value as number}</span>
          </Card>
        ))}
      </div>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-[var(--color-border-soft)] px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {Object.keys(STYLES).map((t) => (
              <Badge key={t} tone="neutral">
                <span
                  className="mr-1 inline-block h-2 w-2 rounded-full"
                  style={{ background: STYLES[t].border }}
                />
                {t}
              </Badge>
            ))}
          </div>
          <span className="text-xs text-[var(--color-faint)]">
            {nodes.length} nodes · {edges.length} edges
          </span>
        </div>
        <div className="h-[70vh] w-full">
          {nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--color-muted)]">
              The blackboard is empty. Load the demo scenario or upload documents.
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              minZoom={0.2}
              proOptions={{ hideAttribution: true }}
              nodesDraggable
              nodesConnectable={false}
              onNodeClick={(_, node) => {
                const rec = recordOf(node.data.raw as Record<string, unknown>);
                if (rec) setSelected({ type: rec.type, id: rec.id, label: node.data.label as string });
              }}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1a2440" />
              <Controls className="!bg-[var(--color-surface)] !border-[var(--color-border)]" />
              <MiniMap
                pannable
                zoomable
                style={{ background: "#0b1122" }}
                nodeColor={(n) => {
                  const t = (n.data as any)?.node_type as string;
                  return STYLES[t]?.border ?? "#334166";
                }}
              />
            </ReactFlow>
          )}
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-[var(--color-border-soft)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">Recent events</h3>
            <span className="text-xs text-[var(--color-faint)]">agent · record · time</span>
          </div>
          <div className="max-h-[420px] overflow-y-auto px-4">
            {recentEvents.length === 0 ? (
              <p className="py-8 text-center text-sm text-[var(--color-muted)]">
                No events yet. Run an investigation to populate the event log.
              </p>
            ) : (
              recentEvents.map((e) => <EventRow key={e.id} event={e} />)
            )}
          </div>
        </Card>

        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-[var(--color-border-soft)] px-4 py-3">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">
              {selected ? "Selected record" : "Record inspector"}
            </h3>
            {selected &&
              (() => {
                const path = recordPath(selected.type, selected.id);
                return path ? (
                  <Button variant="ghost" size="sm" onClick={() => navigate(path)}>
                    Open <ExternalLink size={13} />
                  </Button>
                ) : null;
              })()}
          </div>
          <div className="max-h-[420px] overflow-y-auto px-4 py-3">
            {!selected ? (
              <p className="py-8 text-center text-sm text-[var(--color-muted)]">
                Click a node in the graph to see why it was created and which records it is
                connected to.
              </p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Badge tone="primary">{selected.type}</Badge>
                  <span className="text-xs text-[var(--color-faint)]">#{selected.id}</span>
                  <span className="text-sm text-[var(--color-ink)]">{selected.label}</span>
                </div>

                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
                    Why it exists
                  </p>
                  {trace.loading && !trace.data ? (
                    <p className="text-xs text-[var(--color-muted)]">Loading provenance…</p>
                  ) : trace.data?.why?.length ? (
                    <ul className="ml-4 list-disc space-y-1 text-xs text-[var(--color-muted)]">
                      {trace.data.why.map((reason, i) => (
                        <li key={i}>{reason}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-[var(--color-muted)]">No recorded provenance yet.</p>
                  )}
                </div>

                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
                    Connected records
                  </p>
                  {connected.loading && !connected.data ? (
                    <p className="text-xs text-[var(--color-muted)]">Loading connections…</p>
                  ) : connected.data?.length ? (
                    <ul className="space-y-1 text-xs">
                      {connected.data.map((c) => (
                        <li key={c.relation_id} className="flex items-center gap-2">
                          <span className="text-[var(--color-muted)]">{c.label}</span>
                          <button
                            className="focus-ring rounded text-[var(--color-primary-soft)] hover:underline"
                            onClick={() =>
                              setSelected({
                                type: c.other.type,
                                id: c.other.id,
                                label: `${c.other.type} ${c.other.id}`,
                              })
                            }
                          >
                            {c.other.type} {c.other.id}
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-[var(--color-muted)]">No connections recorded.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
