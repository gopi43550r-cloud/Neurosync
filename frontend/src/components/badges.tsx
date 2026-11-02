import type { ReactNode } from "react";
import { cn, humanize, titleCase } from "../lib/format";

export function Badge({
  children,
  tone = "neutral",
  className,
  dot,
}: {
  children: ReactNode;
  tone?:
    | "neutral"
    | "primary"
    | "success"
    | "warning"
    | "danger"
    | "critical"
    | "info"
    | "violet";
  className?: string;
  dot?: boolean;
}) {
  const tones = {
    neutral: "border-[var(--color-border)] text-[var(--color-muted)] bg-[var(--color-surface-2)]/60",
    primary: "border-[var(--color-primary)]/40 text-[var(--color-primary-soft)] bg-[var(--color-primary)]/10",
    success: "border-[var(--color-success)]/40 text-[var(--color-success)] bg-[var(--color-success)]/10",
    warning: "border-[var(--color-warning)]/40 text-[var(--color-warning)] bg-[var(--color-warning)]/10",
    danger: "border-[var(--color-danger)]/40 text-[var(--color-danger)] bg-[var(--color-danger)]/10",
    critical: "border-[var(--color-critical)]/50 text-[var(--color-critical)] bg-[var(--color-critical)]/15",
    info: "border-[var(--color-info)]/40 text-[var(--color-info)] bg-[var(--color-info)]/10",
    violet: "border-[var(--color-violet)]/40 text-[var(--color-violet)] bg-[var(--color-violet)]/10",
  };
  const dotTones = {
    neutral: "bg-[var(--color-muted)]",
    primary: "bg-[var(--color-primary-soft)]",
    success: "bg-[var(--color-success)]",
    warning: "bg-[var(--color-warning)]",
    danger: "bg-[var(--color-danger)]",
    critical: "bg-[var(--color-critical)]",
    info: "bg-[var(--color-info)]",
    violet: "bg-[var(--color-violet)]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", dotTones[tone])} />}
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const tone =
    severity === "critical"
      ? "critical"
      : severity === "high"
      ? "danger"
      : severity === "medium"
      ? "warning"
      : "neutral";
  return (
    <Badge tone={tone} dot>
      {titleCase(severity)}
    </Badge>
  );
}

export function ConflictStatusBadge({ status }: { status: string }) {
  const tone =
    status === "resolved"
      ? "success"
      : status === "investigating"
      ? "info"
      : status === "human_review"
      ? "violet"
      : status === "inconclusive"
      ? "warning"
      : "neutral";
  return <Badge tone={tone}>{titleCase(status)}</Badge>;
}

export function HypothesisStatusBadge({ status }: { status: string }) {
  const tone =
    status === "supported"
      ? "success"
      : status === "contradicted"
      ? "danger"
      : status === "review_required"
      ? "warning"
      : status === "human_reviewed"
      ? "violet"
      : status === "inconclusive"
      ? "warning"
      : "info";
  return <Badge tone={tone}>{titleCase(status)}</Badge>;
}

export function VerificationBadge({ status }: { status: string }) {
  const tone =
    status === "verified"
      ? "success"
      : status === "partially_verified"
      ? "info"
      : status === "unsupported"
      ? "danger"
      : status === "requires_review"
      ? "warning"
      : "neutral";
  return <Badge tone={tone}>{titleCase(status)}</Badge>;
}

export function FactVerdictBadge({ verdict }: { verdict: string }) {
  const tone =
    verdict === "supported"
      ? "success"
      : verdict === "contradicted"
      ? "danger"
      : verdict === "partially_supported"
      ? "warning"
      : "neutral";
  return <Badge tone={tone}>{titleCase(verdict)}</Badge>;
}

export function CredibilityBadge({
  level,
  score,
}: {
  level: string;
  score?: number | null;
}) {
  const tone =
    level === "well_documented"
      ? "success"
      : level === "partially_documented"
      ? "info"
      : level === "limited_documentation"
      ? "warning"
      : "neutral";
  const label =
    level === "well_documented"
      ? "Well documented"
      : level === "partially_documented"
      ? "Partially documented"
      : level === "limited_documentation"
      ? "Limited documentation"
      : "Unverifiable";
  return (
    <Badge tone={tone}>
      {label}
      {typeof score === "number" ? ` · ${(score * 100).toFixed(0)}%` : " · no score"}
    </Badge>
  );
}

export function InvestigationStatusBadge({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "primary"
      : status === "completed"
      ? "success"
      : status === "paused"
      ? "warning"
      : status === "error"
      ? "danger"
      : status === "cancelled"
      ? "neutral"
      : "info";
  return (
    <Badge tone={tone} dot={status === "running"}>
      {status === "running" ? "Running" : titleCase(status)}
    </Badge>
  );
}

export function AgentStateBadge({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "primary"
      : status === "completed"
      ? "success"
      : status === "failed"
      ? "danger"
      : status === "waiting_for_evidence"
      ? "warning"
      : status === "awaiting_human_review"
      ? "violet"
      : "neutral";
  return (
    <Badge tone={tone} dot={status === "running"}>
      {titleCase(status)}
    </Badge>
  );
}

export function ClaimTypeBadge({ type }: { type: string }) {
  return <Badge tone="primary">{humanize(type)}</Badge>;
}
