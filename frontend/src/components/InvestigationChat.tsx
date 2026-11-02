import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Bot,
  Info,
  MessageSquare,
  Quote,
  Send,
  ShieldCheck,
  TriangleAlert,
  User,
} from "lucide-react";
import { api } from "../api/client";
import type { ChatAnswer } from "../api/types";
import { useApi } from "../hooks/useApi";
import { Badge } from "../components/badges";
import { Button, Card, Spinner } from "../components/ui";
import { cn, titleCase } from "../lib/format";

const FALLBACK_SUGGESTIONS = [
  "Summarise this investigation.",
  "Why was this conflict detected?",
  "Which document supports this claim?",
  "What evidence contradicts this hypothesis?",
  "Why is the investigation inconclusive?",
  "What additional evidence is required?",
];

type Turn =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; answer: ChatAnswer }
  | { id: number; role: "error"; text: string };

let nextTurnId = 1;

function truncate(value: string, length: number): string {
  if (value.length <= length) return value;
  return `${value.slice(0, length).trimEnd()}…`;
}

function AnswerCitations({ answer }: { answer: ChatAnswer }) {
  if (answer.citations.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5 border-t border-[var(--color-border-soft)] pt-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-faint)]">
        Sources cited
      </p>
      {answer.citations.map((citation) => (
        <div key={citation.number} className="flex gap-2 text-xs">
          <span className="mt-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-[var(--color-primary)]/15 px-1 font-semibold tabular-nums text-[var(--color-primary-soft)]">
            {citation.number}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-medium text-[var(--color-ink)]">
                {citation.label}
              </span>
              {citation.document_id ? (
                <Link
                  to={citation.link ?? `/documents/${citation.document_id}`}
                  className="inline-flex items-center gap-1 text-[var(--color-primary-soft)] hover:underline"
                >
                  {citation.document_filename ?? `Document #${citation.document_id}`}
                  <ArrowUpRight size={11} />
                </Link>
              ) : (
                <span className="text-[var(--color-faint)]">
                  stored {titleCase(citation.kind)} record
                </span>
              )}
              <span className="text-[var(--color-faint)]">
                {citation.text_location}
              </span>
            </div>
            {citation.snippet && (
              <p className="mt-0.5 text-[var(--color-muted)]">
                “{truncate(citation.snippet, 220)}”
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function AnswerBody({ answer }: { answer: ChatAnswer }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="primary">{titleCase(answer.intent)}</Badge>
        {answer.insufficient_information ? (
          <Badge tone="warning">Records could not fully answer</Badge>
        ) : (
          <Badge tone="success">Grounded in stored records</Badge>
        )}
        <span className="text-[11px] text-[var(--color-faint)]">
          {answer.citations.length} citation(s)
        </span>
      </div>

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink)]">
        {answer.answer}
      </p>

      {answer.insufficient_information && (
        <div className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 p-2.5 text-xs text-[var(--color-warning)]">
          <p className="flex items-center gap-1.5 font-medium">
            <TriangleAlert size={13} /> The stored records do not fully answer this
            question
          </p>
          {answer.missing_information.length > 0 && (
            <ul className="mt-1 space-y-1">
              {answer.missing_information.slice(0, 6).map((item, index) => (
                <li key={index}>• {item}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!answer.insufficient_information && answer.missing_information.length > 0 && (
        <details className="text-xs text-[var(--color-muted)]">
          <summary className="cursor-pointer select-none text-[var(--color-faint)]">
            Recorded gaps and caveats
          </summary>
          <ul className="mt-1 space-y-1">
            {answer.missing_information.slice(0, 8).map((item, index) => (
              <li key={index}>• {item}</li>
            ))}
          </ul>
        </details>
      )}

      <AnswerCitations answer={answer} />

      {answer.follow_up_questions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {answer.follow_up_questions.map((question) => (
            <FollowUp key={question} question={question} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--color-faint)]">
        <span>
          Grounded in{" "}
          {Object.entries(answer.data_sources)
            .filter(([, count]) => count > 0)
            .map(([key, count]) => `${count} ${key}`)
            .join(" · ") || "no stored rows"}
        </span>
        <details>
          <summary className="cursor-pointer select-none">How this works</summary>
          <p className="mt-1 max-w-3xl text-[var(--color-muted)]">
            {answer.methodology}
          </p>
          <p className="mt-1 max-w-3xl">{answer.caveat}</p>
        </details>
      </div>
    </div>
  );
}

// Follow-up buttons need the parent's send handler. A tiny context-free approach
// keeps the component tree simple: dispatch a custom event the panel listens to.
function FollowUp({ question }: { question: string }) {
  return (
    <button
      onClick={() =>
        window.dispatchEvent(
          new CustomEvent("neurosync:chat-question", { detail: question })
        )
      }
      className="focus-ring rounded-full border border-[var(--color-border)] bg-[var(--color-surface-2)]/60 px-2.5 py-1 text-[11px] text-[var(--color-muted)] transition hover:border-[var(--color-primary-soft)] hover:text-[var(--color-ink)]"
    >
      {question}
    </button>
  );
}

export function InvestigationChatPanel({
  investigationId,
}: {
  investigationId: number;
}) {
  const suggestions = useApi(
    () => api.investigationChatSuggestions(investigationId),
    [investigationId]
  );
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTurns([]);
    setInput("");
  }, [investigationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns, busy]);

  const ask = async (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    setInput("");
    setTurns((current) => [
      ...current,
      { id: nextTurnId++, role: "user", text: question },
    ]);
    setBusy(true);
    try {
      const answer = await api.investigationChat(investigationId, { question });
      setTurns((current) => [
        ...current,
        { id: nextTurnId++, role: "assistant", answer },
      ]);
    } catch (error) {
      setTurns((current) => [
        ...current,
        {
          id: nextTurnId++,
          role: "error",
          text:
            error instanceof Error
              ? error.message
              : "The assistant could not answer that question.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (typeof detail === "string") void ask(detail);
    };
    window.addEventListener("neurosync:chat-question", handler);
    return () => window.removeEventListener("neurosync:chat-question", handler);
  });

  const chips = suggestions.data?.suggestions ?? FALLBACK_SUGGESTIONS;

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-[var(--color-ink)]">
            <MessageSquare size={17} className="text-[var(--color-primary-soft)]" />
            Investigation assistant
          </h2>
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">
            Ask about this investigation's conflicts, claims, evidence and
            conclusions. Answers use only its stored records and cite them.
          </p>
        </div>
        <Badge tone="success">
          <span className="inline-flex items-center gap-1">
            <ShieldCheck size={11} /> grounded
          </span>
        </Badge>
      </div>

      {turns.length === 0 && (
        <div className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-ink)]">
            <Info size={13} /> Try one of these questions
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {chips.slice(0, 6).map((question) => (
              <button
                key={question}
                onClick={() => void ask(question)}
                disabled={busy}
                className="focus-ring rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1 text-[11px] text-[var(--color-muted)] transition hover:border-[var(--color-primary-soft)] hover:text-[var(--color-ink)] disabled:opacity-50"
              >
                {question}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-[var(--color-faint)]">
            You can also name a record id, for example “Which document supports
            claim #4?”.
          </p>
        </div>
      )}

      <div className="max-h-[32rem] space-y-3 overflow-y-auto pr-1">
        {turns.map((turn) => {
          if (turn.role === "user") {
            return (
              <div key={turn.id} className="flex justify-end gap-2">
                <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-[var(--color-primary)]/15 px-3 py-2 text-sm text-[var(--color-ink)]">
                  {turn.text}
                </div>
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-surface-2)] text-[var(--color-muted)]">
                  <User size={13} />
                </div>
              </div>
            );
          }
          if (turn.role === "error") {
            return (
              <div
                key={turn.id}
                className="rounded-lg border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 p-2.5 text-xs text-[var(--color-danger)]"
              >
                {turn.text}
              </div>
            );
          }
          return (
            <div key={turn.id} className="flex gap-2">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)]/15 text-[var(--color-primary-soft)]">
                <Bot size={13} />
              </div>
              <div
                className={cn(
                  "min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3"
                )}
              >
                <AnswerBody answer={turn.answer} />
              </div>
            </div>
          );
        })}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
            <Spinner /> Reading the investigation's stored records…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex items-end gap-2 border-t border-[var(--color-border-soft)] pt-3">
        <div className="flex min-h-[2.5rem] flex-1 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2">
          <Quote size={14} className="shrink-0 text-[var(--color-faint)]" />
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void ask(input);
              }
            }}
            rows={1}
            placeholder="Ask about a conflict, claim, hypothesis, evidence gap…"
            className="max-h-28 w-full resize-none bg-transparent text-sm outline-none placeholder:text-[var(--color-faint)]"
          />
        </div>
        <Button
          onClick={() => void ask(input)}
          disabled={busy || input.trim().length === 0}
          size="sm"
          className="h-10"
        >
          {busy ? <Spinner /> : <Send size={14} />} Ask
        </Button>
      </div>

      {suggestions.error && (
        <p className="text-[11px] text-[var(--color-faint)]">
          Context suggestions are unavailable, but you can still ask a question.
        </p>
      )}
    </Card>
  );
}
