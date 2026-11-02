import { useEffect, useMemo, useState } from "react";
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
import { ExternalLink, RefreshCw, Route, Share2 } from "lucide-react";
import { api } from "../api/client";
import type { KGEdge, KGNode, KnowledgeGraph } from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge } from "../components/badges";
import { Button, Card, EmptyState, ErrorState, Loading, SectionHeader, Spinner } from "../components/ui";
import { cn } from "../lib/format";

const COLUMN: Record<string, number> = {
  document: 0,
  claim: 1,
  conflict: 2,
  evidence: 3,
  hypothesis: 4,
  conclusion: 5,
  investigation: 6,
  agent: 7,
};

const STYLES: Record<string, { border: string; bg: string; text: string }> = {
  document: { border: "#60a5fa", bg: "rgba(96,165,250,0.12)", text: "#93c5fd" },
  claim: { border: "#64719a", bg: "rgba(100,113,154,0.12)", text: "#cbd5e1" },
  conflict: { border: "#f87171", bg: "rgba(248,113,113,0.12)", text: "#fca5a5" },
  evidence: { border: "#34d399", bg: "rgba(52,211,153,0.12)", text: "#6ee7b7" },
  hypothesis: { border: "#fbbf24", bg: "rgba(251,191,36,0.12)", text: "#fcd34d" },
  conclusion: { border: "#a855f7", bg: "rgba(168,85,247,0.14)", text: "#d8b4fe" },
  investigation: { border: "#38bdf8", bg: "rgba(56,189,248,0.12)", text: "#7dd3fc" },
  agent: { border: "#c084fc", bg: "rgba(192,132,252,0.12)", text: "#d8b4fe" },
};

const EDGE_COLORS: Record<string, string> = {
  contains: "#334166",
  supported_by: "#34d399",
  contradicts: "#f87171",
  concerns: "#f87171",
  supports: "#22c55e",
  challenges: "#fb923c",
  gathered_for: "#0ea5e9",
  explains: "#fbbf24",
  concludes: "#a855f7",
  created: "#c084fc",
  derived_from: "#818cf8",
  investigated_in: "#38bdf8",
  investigates: "#38bdf8",
};

const PATH_EDGE_TYPES = new Set(["derived_from", "supports", "challenges", "supported_by"]);

const RAW_KEYS: [string, string][] = [
  ["conflict_id", "conflict"],
  ["evidence_id", "evidence"],
  ["hypothesis_id", "hypothesis"],
  ["conclusion_id", "conclusion"],
  ["claim_id", "claim"],
  ["document_id", "document"],
];

const MINIMAP_LIMIT = 250;

type Selected = { node: KGNode } | null;

function recordPath(type: string, id: number): string | null {
  if (type === "document") return `/documents/${id}`;
  if (type === "conflict") return `/conflicts/${id}`;
  if (type === "investigation") return `/investigations/${id}`;
  return null;
}

function nodeKey(node: KGNode): { type: string; id: number | null } {
  const [type, raw] = node.id.split(":", 2);
  return { type, id: type === "agent" ? null : Number(raw) };
}

// Backward reachability from a conclusion over reasoning edges: highlights the
// evidential chain that feeds the decision.
function evidencePath(graph: KnowledgeGraph, conclusionId: string): Set<string> {
  const visited = new Set<string>([conclusionId]);
  const reasoning = graph.edges.filter((e) => PATH_EDGE_TYPES.has(e.edge_type));
  let frontier = [conclusionId];
  const seenEdges = new Set<string>();
  while (frontier.length) {
    const next: string[] = [];
    for (const current of frontier) {
      for (const edge of reasoning) {
        if (edge.source === current && !visited.has(edge.target)) {
          visited.add(edge.target);
          next.push(edge.target);
        } else if (edge.target === current && !visited.has(edge.source)) {
          visited.add(edge.source);
          next.push(edge.source);
        }
        if (edge.source === current || edge.target === current) seenEdges.add(edge.id);
      }
    }
    frontier = next;
  }
  for (const edge of reasoning) {
    if (visited.has(edge.source) && visited.has(edge.target)) visited.add(`edge:${edge.id}`);
  }
  return visited;
}

function KGNodeBox({ data }: NodeProps) {
  const type = (data.node_type as string) ?? "claim";
  const s = STYLES[type] ?? STYLES.claim;
  const dim = Boolean(data.dim);
  const onPath = Boolean(data.onPath);
  return (
    <div
      style={{
        borderColor: onPath ? "#facc15" : s.border,
        background: s.bg,
        color: "#eef2ff",
        borderRadius: 12,
        borderWidth: onPath ? 2 : 1,
        borderStyle: "solid",
        padding: "8px 12px",
        width: 180,
        fontSize: 12,
        opacity: dim ? 0.25 : 1,
        boxShadow: onPath ? "0 0 0 3px rgba(250,204,21,0.25)" : "0 8px 24px rgba(0,0,0,0.35)",
        transition: "opacity 0.15s ease, border-color 0.15s ease",
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

const nodeTypes = { kg: KGNodeBox };

export default function KnowledgeGraphPage() {
  const [investigationId, setInvestigationId] = useState<number | null>(null);
  const [recordTypes, setRecordTypes] = useState<Set<string>>(new Set());
  const [relationTypes, setRelationTypes] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Selected>(null);
  const [showPath, setShowPath] = useState(true);

  const investigations = useApi(() => api.listInvestigations({ page_size: 100 }), []);

  const { data, loading, error, refetch } = useApi(
    () =>
      api.knowledgeGraph({
        investigation_id: investigationId ?? undefined,
        record_type: recordTypes.size ? [...recordTypes] : undefined,
        relation_type: relationTypes.size ? [...relationTypes] : undefined,
      }),
    [investigationId, [...recordTypes].sort().join(","), [...relationTypes].sort().join(",")]
  );

  const trace = useApi(
    () => {
      const k = selected ? nodeKey(selected.node) : null;
      if (!k || !k.id || k.type === "agent" || k.type === "investigation") {
        return Promise.resolve(null);
      }
      return api.blackboardTrace(k.type, k.id, investigationId ?? undefined);
    },
    [selected?.node.id, investigationId],
    { enabled: !!selected }
  );

  const pathNodes = useMemo(() => {
    if (!data || !selected || !showPath) return new Set<string>();
    const k = nodeKey(selected.node);
    if (k.type !== "conclusion") return new Set<string>();
    return evidencePath(data, selected.node.id);
  }, [data, selected, showPath]);

  const pathActive = pathNodes.size > 0;

  const { nodes, edges } = useMemo(() => {
    const graph = data ?? { nodes: [], edges: [] };
    const counters: Record<number, number> = {};

    const rfNodes: Node[] = [...graph.nodes]
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((n) => {
        const col = COLUMN[n.node_type] ?? 3;
        counters[col] = (counters[col] ?? 0) + 1;
        const row = counters[col] - 1;
        const onPath = pathNodes.has(n.id);
        return {
          id: n.id,
          type: "kg",
          position: { x: col * 250, y: row * 92 },
          data: {
            label: n.label,
            node_type: n.node_type,
            onPath,
            dim: pathActive && !onPath,
          },
        };
      });

    const rfEdges: Edge[] = graph.edges.map((e: KGEdge) => {
      const onPath = pathNodes.has(`edge:${e.id}`) && pathNodes.has(e.source) && pathNodes.has(e.target);
      const highlighted = pathActive && onPath;
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        animated: highlighted || e.edge_type === "contradicts",
        style: {
          stroke: highlighted ? "#facc15" : EDGE_COLORS[e.edge_type] ?? "#334166",
          strokeWidth: highlighted ? 2.5 : 1,
          strokeDasharray: e.verified ? undefined : "6 4",
          opacity: pathActive && !onPath ? 0.12 : 0.9,
        },
      };
    });

    return { nodes: rfNodes, edges: rfEdges };
  }, [data, pathNodes, pathActive]);

  useEffect(() => {
    // Drop a selection that is no longer part of the (filtered) graph.
    if (selected && data && !data.nodes.some((n) => n.id === selected.node.id)) {
      setSelected(null);
    }
  }, [data, selected]);

  function toggle(set: Set<string>, value: string, apply: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  }

  if (loading && !data) return <Loading label="Building knowledge graph…" />;
  if (error && !data) return <ErrorState message={error} onRetry={refetch} />;

  const counts = data?.node_type_counts ?? {};
  const relCounts = data?.relation_type_counts ?? {};
  const availableTypes = data?.available_node_types ?? [];
  const availableRelations = data?.available_relation_types ?? [];
  const isEmpty = !!data && data.nodes.length === 0;
  const selectedKey = selected ? nodeKey(selected.node) : null;

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Knowledge Graph"
        subtitle="Every node is a persisted record and every edge is backed by a stored relationship — verified links are solid, inferred links are dashed."
        action={
          <Button variant="outline" size="sm" onClick={refetch}>
            {loading ? <Spinner /> : <RefreshCw size={14} />} Refresh
          </Button>
        }
      />

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
            Investigation
            <select
              value={investigationId ?? ""}
              onChange={(e) => setInvestigationId(e.target.value ? Number(e.target.value) : null)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5 text-xs text-[var(--color-ink)] outline-none"
            >
              <option value="">All investigations</option>
              {(investigations.data?.items ?? []).map((inv) => (
                <option key={inv.id} value={inv.id}>
                  #{inv.id} · {inv.name}
                </option>
              ))}
            </select>
          </label>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-[var(--color-faint)]">Records</span>
            {availableTypes.map((t) => (
              <button
                key={t}
                onClick={() => toggle(recordTypes, t, setRecordTypes)}
                className={cn(
                  "focus-ring rounded-full border px-2 py-0.5 text-[11px] transition",
                  recordTypes.has(t)
                    ? "border-[var(--color-primary-soft)] bg-[var(--color-primary)]/20 text-[var(--color-ink)]"
                    : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-ink)]"
                )}
              >
                {t} {counts[t] ? `(${counts[t]})` : ""}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-[var(--color-faint)]">Relations</span>
            {availableRelations.map((t) => (
              <button
                key={t}
                onClick={() => toggle(relationTypes, t, setRelationTypes)}
                className={cn(
                  "focus-ring rounded-full border px-2 py-0.5 text-[11px] transition",
                  relationTypes.has(t)
                    ? "border-[var(--color-primary-soft)] bg-[var(--color-primary)]/20 text-[var(--color-ink)]"
                    : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-ink)]"
                )}
              >
                {t} {relCounts[t] ? `(${relCounts[t]})` : ""}
              </button>
            ))}
          </div>

          {(recordTypes.size > 0 || relationTypes.size > 0 || investigationId != null) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setRecordTypes(new Set());
                setRelationTypes(new Set());
                setInvestigationId(null);
              }}
            >
              Clear filters
            </Button>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border-soft)] pt-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1.5 text-[11px] text-[var(--color-muted)]">
              <svg width="26" height="8">
                <line x1="0" y1="4" x2="26" y2="4" stroke="#8b98b8" strokeWidth="2" />
              </svg>
              verified
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-[var(--color-muted)]">
              <svg width="26" height="8">
                <line x1="0" y1="4" x2="26" y2="4" stroke="#8b98b8" strokeWidth="2" strokeDasharray="6 4" />
              </svg>
              inferred
            </span>
            {selectedKey?.type === "conclusion" && (
              <Button variant={showPath ? "primary" : "outline"} size="sm" onClick={() => setShowPath((v) => !v)}>
                <Route size={13} /> Evidence path
              </Button>
            )}
          </div>
          <span className="text-xs text-[var(--color-faint)]">
            {nodes.length} nodes · {edges.length} edges
            {data?.truncated ? " · truncated" : ""}
          </span>
        </div>

        {data?.truncated && (
          <div className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 px-3 py-2 text-xs text-[var(--color-muted)]">
            Showing a capped subset ({data.totals.nodes} nodes / {data.totals.edges} edges total).
            Narrow the filters or pick an investigation to see everything.
          </div>
        )}
      </Card>

      <Card className="p-0">
        <div className="h-[70vh] w-full">
          {isEmpty ? (
            <EmptyState
              icon={<Share2 size={22} />}
              title="The knowledge graph is empty"
              description="No persisted records are available yet. Load the demo scenario or run an investigation to populate the graph."
            />
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              minZoom={0.15}
              proOptions={{ hideAttribution: true }}
              nodesDraggable
              nodesConnectable={false}
              onlyRenderVisibleElements
              onNodeClick={(_, node) => {
                const found = data?.nodes.find((n) => n.id === node.id);
                if (found) setSelected({ node: found });
              }}
              onPaneClick={() => setSelected(null)}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1a2440" />
              <Controls className="!bg-[var(--color-surface)] !border-[var(--color-border)]" />
              {nodes.length <= MINIMAP_LIMIT && (
                <MiniMap
                  pannable
                  zoomable
                  style={{ background: "#0b1122" }}
                  nodeColor={(n) => {
                    const t = (n.data as Record<string, unknown>)?.node_type as string;
                    return STYLES[t]?.border ?? "#334166";
                  }}
                />
              )}
            </ReactFlow>
          )}
        </div>
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-[var(--color-border-soft)] px-4 py-3">
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">
            {selected ? "Node details" : "Inspector"}
          </h3>
          {selected &&
            selectedKey?.id &&
            (() => {
              const path = recordPath(selectedKey.type, selectedKey.id);
              return path ? (
                <a
                  href={path}
                  className="focus-ring inline-flex items-center gap-1 text-xs text-[var(--color-primary-soft)] hover:underline"
                >
                  Open <ExternalLink size={13} />
                </a>
              ) : null;
            })()}
        </div>
        <div className="max-h-[420px] overflow-y-auto px-4 py-3">
          {!selected ? (
            <p className="py-8 text-center text-sm text-[var(--color-muted)]">
              Click a node to inspect it. Select a conclusion to highlight the evidence path that
              produced it.
            </p>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Badge tone="primary">{selected.node.node_type}</Badge>
                <span className="text-xs text-[var(--color-faint)]">#{selected.node.id}</span>
                <span className="text-sm text-[var(--color-ink)]">{selected.node.label}</span>
              </div>

              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
                  Attributes
                </p>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                  {Object.entries(selected.node.data).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-[var(--color-faint)]">{k}</dt>
                      <dd className="truncate text-[var(--color-muted)]">
                        {v === null || v === undefined ? "—" : String(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>

              {selectedKey && selectedKey.type !== "agent" && selectedKey.type !== "investigation" && (
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
                    <p className="text-xs text-[var(--color-muted)]">No recorded provenance.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
