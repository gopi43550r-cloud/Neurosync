import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  FileText,
  RefreshCw,
  Trash2,
  Upload,
  Eye,
  FilePlus2,
  ShieldCheck,
} from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pagination,
  SectionHeader,
  Spinner,
} from "../components/ui";
import { Badge } from "../components/badges";
import { SourceCredibilityListPanel } from "../components/SourceCredibility";
import { cn, formatBytes, formatDate } from "../lib/format";

export default function Documents() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "credibility" ? "credibility" : "documents";
  const investigationParam = Number(params.get("investigation_id") ?? "");
  const documentParam = Number(params.get("document_id") ?? "");
  const investigationId =
    Number.isFinite(investigationParam) && investigationParam > 0
      ? investigationParam
      : undefined;
  const documentId =
    Number.isFinite(documentParam) && documentParam > 0 ? documentParam : undefined;
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [page, setPage] = useState(1);
  const { data, loading, error, refetch } = useApi(
    () => api.listDocuments({ page }),
    [page]
  );

  const setTab = (next: "documents" | "credibility") => {
    const updated = new URLSearchParams(params);
    if (next === "documents") updated.delete("tab");
    else updated.set("tab", "credibility");
    setParams(updated, { replace: true });
  };

  const tabs = (
    <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
      <button
        onClick={() => setTab("documents")}
        className={cn(
          "focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
          tab === "documents"
            ? "bg-[var(--color-primary)]/15 text-[var(--color-primary-soft)]"
            : "text-[var(--color-muted)] hover:text-[var(--color-ink)]"
        )}
      >
        <FileText size={13} /> Documents
      </button>
      <button
        onClick={() => setTab("credibility")}
        className={cn(
          "focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
          tab === "credibility"
            ? "bg-[var(--color-primary)]/15 text-[var(--color-primary-soft)]"
            : "text-[var(--color-muted)] hover:text-[var(--color-ink)]"
        )}
      >
        <ShieldCheck size={13} /> Source credibility
      </button>
    </div>
  );

  if (tab === "credibility") {
    return (
      <div className="space-y-6">
        <SectionHeader
          title="Source credibility"
          subtitle="Every source assessed for authenticity, provenance, evidence quality, traceability and consistency. Missing information is reported, never filled in."
          action={tabs}
        />
        <SourceCredibilityListPanel
          investigationId={investigationId}
          documentId={documentId}
        />
      </div>
    );
  }

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true);
    try {
      const results = await api.uploadDocuments(list);
      const totalClaims = results.reduce((n, r) => n + r.claim_count, 0);
      toast.success(
        `Processed ${results.length} file(s) · ${totalClaims} claim(s) extracted.`
      );
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number, name: string) => {
    if (!confirm(`Delete "${name}" and its claims/conflicts?`)) return;
    try {
      await api.deleteDocument(id);
      toast.success("Document deleted.");
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const reprocess = async (id: number) => {
    try {
      await api.reprocessDocument(id);
      toast.success("Document reprocessed.");
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reprocess failed");
    }
  };

  const docs = data?.items ?? [];

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Documents"
        subtitle="Upload evidence sources; claims are extracted automatically."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {tabs}
            <Button size="sm" onClick={() => inputRef.current?.click()}>
              <Upload size={14} /> Upload files
            </Button>
          </div>
        }
      />

      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".txt,.md,.csv,.json,.pdf,.docx"
        className="hidden"
        onChange={(e) => {
          if (e.target.files) upload(e.target.files);
          e.target.value = "";
        }}
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-6 py-10 text-center transition",
          dragging
            ? "border-[var(--color-primary-soft)] bg-[var(--color-primary)]/10"
            : "border-[var(--color-border)] bg-[var(--color-surface)]/40 hover:border-[var(--color-primary)]/50"
        )}
      >
        {busy ? (
          <Spinner className="text-[var(--color-primary-soft)]" />
        ) : (
          <FilePlus2 size={22} className="text-[var(--color-primary-soft)]" />
        )}
        <p className="text-sm font-medium">
          {busy ? "Processing…" : "Drag & drop files here, or click to browse"}
        </p>
        <p className="text-xs text-[var(--color-faint)]">
          Supports .txt, .md, .csv, .json, .pdf, .docx
        </p>
      </div>

      {loading && !data ? (
        <Loading />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : docs.length === 0 ? (
        <EmptyState
          title="No documents yet"
          description="Upload files or load the demonstration scenario from the Overview page."
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border-soft)] text-left text-xs uppercase tracking-wide text-[var(--color-faint)]">
                <th className="px-4 py-3 font-medium">File</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Claims</th>
                <th className="px-4 py-3 font-medium">Conflicts</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">Uploaded</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border-soft)]">
              {docs.map((d) => (
                <tr key={d.id} className="hover:bg-[var(--color-surface-2)]/40">
                  <td className="max-w-xs px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileText size={15} className="shrink-0 text-[var(--color-faint)]" />
                      <Link
                        to={`/documents/${d.id}`}
                        className="truncate font-medium hover:text-[var(--color-primary-soft)]"
                      >
                        {d.filename}
                      </Link>
                      {d.is_demo && <Badge tone="info">demo</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      tone={
                        d.status === "processed"
                          ? "success"
                          : d.status === "error"
                          ? "danger"
                          : "warning"
                      }
                    >
                      {d.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 tabular-nums text-[var(--color-muted)]">
                    {d.claim_count}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-[var(--color-muted)]">
                    {d.conflict_count}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-faint)]">
                    {formatBytes(d.file_size)}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-faint)]">
                    {formatDate(d.uploaded_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <Link to={`/documents/${d.id}`}>
                        <Button variant="ghost" size="sm" title="View">
                          <Eye size={14} />
                        </Button>
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Reprocess"
                        onClick={() => reprocess(d.id)}
                      >
                        <RefreshCw size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Delete"
                        onClick={() => remove(d.id, d.filename)}
                      >
                        <Trash2 size={14} className="text-[var(--color-danger)]" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination
            page={data?.page ?? page}
            pageSize={data?.page_size ?? 50}
            total={data?.total ?? 0}
            onPageChange={setPage}
            className="border-t border-[var(--color-border-soft)] px-4 py-3"
          />
        </Card>
      )}
    </div>
  );
}
