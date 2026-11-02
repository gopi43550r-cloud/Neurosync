import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Bot,
  FileText,
  FlaskConical,
  History,
  LayoutDashboard,
  Lightbulb,
  Network,
  Radar,
  Share2,
  ScrollText,
  Search as SearchIcon,
  Settings,
  TriangleAlert,
  Cpu,
} from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { cn } from "../lib/format";
import { Badge } from "./badges";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/conflicts", label: "Conflicts", icon: TriangleAlert },
  { to: "/blackboard", label: "Blackboard", icon: Network },
  { to: "/knowledge-graph", label: "Knowledge Graph", icon: Share2 },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/hypotheses", label: "Hypotheses", icon: Lightbulb },
  { to: "/evidence", label: "Evidence", icon: FlaskConical },
  { to: "/investigations", label: "Investigations", icon: Radar },
  { to: "/reports", label: "Reports", icon: ScrollText },
  { to: "/audit", label: "Audit Trail", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { data } = useApi(
    () => (q.trim().length >= 2 ? api.search(q.trim()) : Promise.resolve(null)),
    [q],
    { enabled: q.trim().length >= 2 }
  );

  const groups: { key: string; label: string; route: (id: number) => string }[] = [
    { key: "documents", label: "Documents", route: (id) => `/documents/${id}` },
    { key: "conflicts", label: "Conflicts", route: (id) => `/conflicts/${id}` },
    { key: "hypotheses", label: "Hypotheses", route: () => `/hypotheses` },
    { key: "evidence", label: "Evidence", route: () => `/evidence` },
    { key: "investigations", label: "Investigations", route: (id) => `/investigations/${id}` },
  ];

  const go = (route: string) => {
    setOpen(false);
    setQ("");
    navigate(route);
  };

  return (
    <div className="relative w-full max-w-md">
      <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]/60 px-3 py-2">
        <SearchIcon size={15} className="text-[var(--color-faint)]" />
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search documents, conflicts, hypotheses…"
          className="w-full bg-transparent text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)]"
        />
      </div>
      {open && q.trim().length >= 2 && (
        <div className="absolute z-40 mt-2 w-full overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl">
          {!data ? (
            <p className="px-4 py-3 text-sm text-[var(--color-muted)]">Searching…</p>
          ) : (
            <div className="max-h-80 overflow-auto py-1">
              {groups.map((g) => {
                const items = (data[g.key] ?? []) as { id: number; label: string }[];
                if (!items.length) return null;
                return (
                  <div key={g.key} className="py-1">
                    <p className="px-4 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-faint)]">
                      {g.label}
                    </p>
                    {items.slice(0, 4).map((item) => (
                      <button
                        key={`${g.key}-${item.id}`}
                        onMouseDown={() => go(g.route(item.id))}
                        className="block w-full truncate px-4 py-1.5 text-left text-sm text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]"
                      >
                        {item.label || `#${item.id}`}
                      </button>
                    ))}
                  </div>
                );
              })}
              {groups.every(
                (g) => !((data[g.key] ?? []) as unknown[]).length
              ) && (
                <p className="px-4 py-3 text-sm text-[var(--color-muted)]">
                  No results for “{q}”.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const { data: health } = useApi(() => api.health(), []);
  const isDemoMode = health ? health.mode === "demonstration" : true;

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-[var(--color-border-soft)] bg-[var(--color-bg-soft)]/70 px-3 py-5 lg:flex">
        <div className="mb-8 flex items-center gap-3 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-accent)] shadow-lg shadow-indigo-900/40">
            <Network size={18} className="text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">NeuroSync</p>
            <p className="text-[11px] text-[var(--color-faint)]">
              Multi-Agent Blackboard
            </p>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-[var(--color-primary)]/15 text-[var(--color-ink)]"
                    : "text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    size={16}
                    className={isActive ? "text-[var(--color-primary-soft)]" : ""}
                  />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-4 rounded-xl border border-[var(--color-border-soft)] bg-[var(--color-surface)]/50 p-3">
          <div className="flex items-center gap-2">
            <Cpu size={14} className="text-[var(--color-faint)]" />
            <span className="text-xs font-medium text-[var(--color-muted)]">
              Reasoning mode
            </span>
          </div>
          <div className="mt-2">
            <Badge tone={isDemoMode ? "info" : "violet"} dot>
              {isDemoMode ? "Deterministic" : "AI-assisted"}
            </Badge>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-faint)]">
            {isDemoMode
              ? "Rule-based analysis. No API key required."
              : `LLM enabled${
                  health?.llm_model ? ` (${health.llm_model})` : ""
                }.`}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-[var(--color-border-soft)] bg-[var(--color-bg)]/80 px-6 py-3 backdrop-blur">
          <div className="lg:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-accent)]">
              <Network size={16} className="text-white" />
            </div>
          </div>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-3">
            <Badge tone={isDemoMode ? "info" : "violet"}>
              {isDemoMode ? "Demo mode" : "AI mode"}
            </Badge>
            <span className="hidden text-xs text-[var(--color-faint)] sm:block">
              v{health?.version ?? "1.0.0"}
            </span>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
