import { useEffect, useState, type FormEvent } from "react";
import {
  Cpu,
  Database,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  RotateCcw,
  Settings2,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import { Button, Card, ErrorState, Loading, SectionHeader } from "../components/ui";
import { Badge } from "../components/badges";
import { percent } from "../lib/format";

export default function Settings() {
  const toast = useToast();
  const navigate = useNavigate();
  const health = useApi(() => api.health(), []);
  const config = useApi(() => api.config(), []);
  const reasoning = useApi(() => api.reasoningSettings(), []);
  const llm = useApi(() => api.llmSettings(), []);
  const [switching, setSwitching] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [savingKey, setSavingKey] = useState(false);

  useEffect(() => {
    if (!llm.data) return;
    setModel(llm.data.model ?? "");
    setBaseUrl(llm.data.base_url ?? "");
  }, [llm.data]);

  if (health.loading && !health.data) return <Loading />;
  if (health.error) return <ErrorState message={health.error} onRetry={health.refetch} />;

  const h = health.data!;
  const c = config.data;
  const r = reasoning.data;

  const changeMode = async (mode: "deterministic" | "ai_assisted") => {
    if (!r || r.reasoning_mode === mode || switching) return;
    setSwitching(true);
    try {
      const res = await api.updateReasoningMode(mode);
      reasoning.setData(res);
      health.refetch();
      toast.success(
        mode === "ai_assisted"
          ? "AI-assisted reasoning selected. Results are validated against the documents."
          : "Deterministic reasoning selected."
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update reasoning mode.");
    } finally {
      setSwitching(false);
    }
  };

  const loadDemo = async () => {
    try {
      const res = await api.loadDemo(false);
      toast.success("Demonstration scenario loaded.");
      navigate(`/investigations/${res.investigation_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  };

  const resetDemo = async () => {
    if (!confirm("Remove all demonstration documents and results?")) return;
    try {
      const res = await api.resetDemo();
      toast.success(res.message);
      health.refetch();
      config.refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  };

  const saveKey = async (event: FormEvent) => {
    event.preventDefault();
    setSavingKey(true);
    try {
      const res = await api.saveLLMSettings({
        api_key: apiKey,
        model: model || undefined,
        base_url: baseUrl || undefined,
        enable_llm: true,
      });
      llm.setData(res);
      setApiKey("");
      setShowKey(false);
      health.refetch();
      config.refetch();
      reasoning.refetch();
      toast.success(
        res.effective_mode === "ai_assisted"
          ? "API key saved. AI-assisted reasoning is active."
          : "API key saved. Select AI-assisted reasoning to use it."
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save the API key.");
    } finally {
      setSavingKey(false);
    }
  };

  const removeKey = async () => {
    if (
      !confirm(
        "Remove the saved OpenAI API key? AI-assisted reasoning will fall back to deterministic mode."
      )
    )
      return;
    setSavingKey(true);
    try {
      const res = await api.clearLLMKey();
      llm.setData(res);
      health.refetch();
      config.refetch();
      reasoning.refetch();
      toast.success("Saved API key removed.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to remove the API key.");
    } finally {
      setSavingKey(false);
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Settings & system"
        subtitle="Reasoning mode, scheduler configuration and demonstration data."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader
            title={
              <span className="inline-flex items-center gap-2">
                <Cpu size={16} /> Reasoning engine
              </span>
            }
          />
          <div className="space-y-3 text-sm">
            <Fact label="Application" value={`${h.app} v${h.version}`} />
            <Fact
              label="Active engine"
              value={
                <Badge tone={r?.effective_mode === "ai_assisted" ? "violet" : "info"} dot>
                  {r?.effective_mode === "ai_assisted" ? "AI-assisted" : "Deterministic"}
                </Badge>
              }
            />
            <Fact
              label="Provider configured"
              value={h.ai_configured ? "Yes" : "No (rule-based only)"}
            />
            {r?.model && <Fact label="Model" value={r.model} />}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-[var(--color-faint)]">
              Reasoning mode
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant={r?.reasoning_mode === "deterministic" ? "primary" : "ghost"}
                disabled={switching}
                onClick={() => changeMode("deterministic")}
              >
                Deterministic
              </Button>
              <Button
                variant={r?.reasoning_mode === "ai_assisted" ? "primary" : "ghost"}
                disabled={switching}
                onClick={() => changeMode("ai_assisted")}
              >
                <Sparkles size={14} /> AI-assisted
              </Button>
            </div>
            {r && (
              <p className="mt-3 text-xs leading-relaxed text-[var(--color-muted)]">{r.note}</p>
            )}
            {r && !r.llm_configured && r.reasoning_mode === "ai_assisted" && (
              <p className="mt-2 text-xs text-[var(--color-warning,var(--color-muted))]">
                Add an OpenAI API key below (or set <code>OPENAI_API_KEY</code> and{" "}
                <code>ENABLE_LLM=true</code> in the backend environment), then
                restart the server if you edited the environment.
              </p>
            )}
          </div>

          <p className="mt-4 flex items-start gap-2 rounded-lg bg-[var(--color-bg-soft)] p-3 text-xs text-[var(--color-muted)]">
            <Info size={14} className="mt-0.5 shrink-0 text-[var(--color-info)]" />
            The app is fully functional without an API key. When AI assistance is off (or
            no provider is configured) it uses transparent rule-based reasoning so every
            result remains reproducible. When AI is on, every model suggestion is validated
            against the document text and cited evidence, and anything ungrounded is
            discarded.
          </p>
        </Card>

        <Card>
          <SectionHeader
            title={
              <span className="inline-flex items-center gap-2">
                <Settings2 size={16} /> Scheduler
              </span>
            }
            subtitle="How agents are prioritized each cycle"
          />
          {c ? (
            <div className="space-y-3 text-sm">
              {Object.entries(c.scheduler_weights).map(([k, v]) => (
                <div key={k}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-[var(--color-muted)]">{k.replace(/_/g, " ")}</span>
                    <span className="text-[var(--color-faint)]">{percent(v as number)}</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                    <div
                      className="h-full rounded-full bg-[var(--color-primary)]"
                      style={{ width: `${(v as number) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
              <div className="grid grid-cols-2 gap-3 pt-2">
                <Fact label="Default iterations" value={String(c.default_iteration_limit)} />
                <Fact label="Default min evidence" value={String(c.default_min_evidence)} />
                <Fact label="Max upload" value={`${c.max_upload_mb} MB`} />
              </div>
            </div>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">Loading configuration…</p>
          )}
        </Card>
      </div>

        <Card>
          <SectionHeader
            title={
              <span className="inline-flex items-center gap-2">
                <KeyRound size={16} /> OpenAI API key (optional)
              </span>
            }
            subtitle="Add a key here to enable AI-assisted reasoning. The key is never shown again after saving and is stored in backend/.env.local."
          />
          <div className="space-y-3 text-sm">
            <div className="grid gap-3 sm:grid-cols-3">
              <Fact label="Status" value={llm.data?.configured ? "Configured" : "Not configured"} />
              <Fact label="Key" value={llm.data?.configured ? llm.data.key_hint : "—"} />
              <Fact label="Source" value={llm.data?.source ?? "none"} />
            </div>
            <Fact label="Model" value={llm.data?.model ?? "—"} />
            <Fact label="Base URL" value={llm.data?.base_url ?? "—"} />
            <Fact label="Saved to" value={llm.data?.storage ?? "backend/.env.local"} />
            {llm.data?.note && (
              <p className="text-xs leading-relaxed text-[var(--color-muted)]">{llm.data.note}</p>
            )}
          </div>

          <form className="mt-4 space-y-3" onSubmit={saveKey}>
            <div className="grid gap-3 lg:grid-cols-3">
              <label className="space-y-1 text-xs text-[var(--color-muted)]">
                <span>API key</span>
                <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
                  <input
                    type={showKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={llm.data?.configured ? "Leave blank to keep existing key" : "sk-..."}
                    autoComplete="off"
                    spellCheck={false}
                    className="w-full bg-transparent text-sm text-[var(--color-ink)] outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    className="text-[var(--color-faint)] hover:text-[var(--color-ink)]"
                  >
                    {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </label>
              <label className="space-y-1 text-xs text-[var(--color-muted)]">
                <span>Model</span>
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="gpt-4o-mini"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-ink)] outline-none"
                />
              </label>
              <label className="space-y-1 text-xs text-[var(--color-muted)]">
                <span>Base URL (OpenAI-compatible)</span>
                <input
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder="https://api.openai.com/v1"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-ink)] outline-none"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={savingKey}>
                <KeyRound size={14} /> {savingKey ? "Saving…" : "Save API key"}
              </Button>
              {llm.data?.configured && llm.data?.source === "saved" && (
                <Button
                  type="button"
                  variant="danger"
                  onClick={removeKey}
                  disabled={savingKey}
                >
                  <Trash2 size={14} /> Remove saved key
                </Button>
              )}
              <span className="text-xs text-[var(--color-faint)]">
                Keys are never returned by the API. Use environment variables to take
                precedence.
              </span>
            </div>
          </form>
        </Card>

        <Card>
          <SectionHeader
            title={
              <span className="inline-flex items-center gap-2">
                <Database size={16} /> Demonstration data
              </span>
            }
            subtitle="A fully labelled industrial diagnostic scenario for evaluation."
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={loadDemo}>
              <Sparkles size={14} /> Load demonstration scenario
            </Button>
            <Button variant="danger" onClick={resetDemo}>
              <RotateCcw size={14} /> Reset demonstration data
            </Button>
            <span className="text-xs text-[var(--color-faint)]">
              Demo records are always marked as demonstration data and can be removed
              without touching your own uploads.
            </span>
          </div>
        </Card>

      <Card>
        <SectionHeader title="About NeuroSync" />
        <p className="text-sm leading-relaxed text-[var(--color-muted)]">
          NeuroSync is an evidence-driven multi-agent investigation workspace built on
          a Blackboard Architecture. Specialized agents — Evidence Collector, Conflict
          Detector, Hypothesis Generator, Investigator, Verification Agent and Decision
          Agent — read from and write to a shared knowledge store. A dynamic scheduler
          selects the most valuable action each cycle based on severity, uncertainty,
          evidence gaps and expected information gain, and every decision is recorded
          with its supporting evidence and reasoning.
        </p>
      </Card>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border-soft)] pb-2">
      <span className="text-xs uppercase tracking-wide text-[var(--color-faint)]">
        {label}
      </span>
      <span className="text-right text-sm text-[var(--color-ink)]">{value}</span>
    </div>
  );
}
