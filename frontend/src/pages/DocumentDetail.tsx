import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, MessageSquareQuote } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  SectionHeader,
} from "../components/ui";
import { Badge } from "../components/badges";
import { SourceCredibilityPanel } from "../components/SourceCredibility";
import { formatBytes, formatDate } from "../lib/format";

export default function DocumentDetail() {
  const { id } = useParams();
  const docId = Number(id);
  const detail = useApi(() => api.getDocument(docId), [docId]);
  const claims = useApi(() => api.listClaims({ document_id: docId, page_size: 200 }), [docId]);

  if (detail.loading && !detail.data) return <Loading />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.refetch} />;
  const doc = detail.data!;

  return (
    <div className="space-y-6">
      <Link to="/documents" className="inline-flex items-center gap-2 text-sm text-[var(--color-muted)] hover:text-[var(--color-ink)]">
        <ArrowLeft size={14} /> All documents
      </Link>

      <SectionHeader
        title={
          <span className="inline-flex items-center gap-2">
            <FileText size={20} /> {doc.filename}
          </span>
        }
        subtitle={`${doc.file_type.toUpperCase()} · ${formatBytes(doc.file_size)} · uploaded ${formatDate(doc.uploaded_at)}`}
        action={
          <div className="flex items-center gap-2">
            {doc.is_demo && <Badge tone="info">demonstration data</Badge>}
            <Badge tone={doc.status === "processed" ? "success" : doc.status === "error" ? "danger" : "warning"}>
              {doc.status}
            </Badge>
          </div>
        }
      />

      {doc.error_message && (
        <Card className="border-[var(--color-danger)]/40 text-sm text-[var(--color-danger)]">
          {doc.error_message}
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--color-faint)]">Claims</p>
          <p className="mt-1 text-2xl font-semibold">{doc.claim_count}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--color-faint)]">Conflicts</p>
          <p className="mt-1 text-2xl font-semibold">{doc.conflict_count}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--color-faint)]">Observations</p>
          <p className="mt-1 text-2xl font-semibold">{doc.observation_count}</p>
        </Card>
        <Card>
          <p className="text-xs uppercase tracking-wide text-[var(--color-faint)]">Characters</p>
          <p className="mt-1 text-2xl font-semibold">{doc.char_count}</p>
        </Card>
      </div>

      <SourceCredibilityPanel documentId={docId} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader title="Extracted text" subtitle="First 4000 characters" />
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--color-bg-soft)] p-4 text-xs leading-relaxed text-[var(--color-muted)]">
            {doc.text_preview || "No text extracted."}
          </pre>
        </Card>

        <Card>
          <SectionHeader
            title="Extracted claims"
            subtitle="Structured assertions derived from this document"
          />
          {claims.loading && !claims.data ? (
            <p className="py-6 text-sm text-[var(--color-muted)]">Loading claims…</p>
          ) : (claims.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No claims extracted"
              description="This document may not contain measurable or factual assertions."
            />
          ) : (
            <ul className="max-h-[420px] space-y-2 overflow-auto pr-1">
              {claims.data!.items.map((c) => (
                <li
                  key={c.id}
                  className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3"
                >
                  <div className="flex items-start gap-2">
                    <MessageSquareQuote size={14} className="mt-0.5 shrink-0 text-[var(--color-primary-soft)]" />
                    <div className="min-w-0">
                      <p className="text-sm text-[var(--color-ink)]">{c.claim_text}</p>
                      <div className="mt-1.5 flex flex-wrap gap-2 text-[11px] text-[var(--color-faint)]">
                        <span>{c.claim_type}</span>
                        {c.subject && <span>· subject: {c.subject}</span>}
                        {c.numeric_value !== null && (
                          <span>
                            · value: {c.numeric_value} {c.unit}
                          </span>
                        )}
                        <span>· conf {(c.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
