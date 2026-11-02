import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { ChevronLeft, ChevronRight, Loader2, Inbox, TriangleAlert } from "lucide-react";
import { cn } from "../lib/format";

export function Card({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("card p-5", className)} {...props}>
      {children}
    </div>
  );
}

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-[var(--color-ink)]">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

type ButtonVariant = "primary" | "ghost" | "outline" | "danger" | "subtle";
type ButtonSize = "sm" | "md";

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  const variants: Record<ButtonVariant, string> = {
    primary:
      "bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-soft)] shadow-lg shadow-indigo-900/30",
    ghost: "text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]",
    outline:
      "border border-[var(--color-border)] text-[var(--color-ink)] hover:border-[var(--color-primary-soft)] hover:bg-[var(--color-surface-2)]",
    danger:
      "border border-[var(--color-danger)]/40 text-[var(--color-danger)] hover:bg-[var(--color-danger)]/10",
    subtle:
      "bg-[var(--color-surface-2)] text-[var(--color-ink)] hover:bg-[var(--color-border)]",
  };
  return (
    <button
      className={cn(
        "focus-ring inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm",
        variants[variant],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin", className)} size={16} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-[var(--color-muted)]">
      <Spinner /> {label}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-surface-2)] text-[var(--color-faint)]">
        {icon ?? <Inbox size={22} />}
      </div>
      <div>
        <p className="font-medium text-[var(--color-ink)]">{title}</p>
        {description && (
          <p className="mt-1 max-w-md text-sm text-[var(--color-muted)]">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-danger)]/10 text-[var(--color-danger)]">
        <TriangleAlert size={22} />
      </div>
      <p className="max-w-md text-sm text-[var(--color-muted)]">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "primary" | "danger" | "success" | "warning";
}) {
  const tones = {
    default: "text-[var(--color-ink)]",
    primary: "text-[var(--color-primary-soft)]",
    danger: "text-[var(--color-danger)]",
    success: "text-[var(--color-success)]",
    warning: "text-[var(--color-warning)]",
  };
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-faint)]">
        {label}
      </span>
      <span className={cn("text-2xl font-semibold tabular-nums", tones[tone])}>
        {value}
      </span>
      {hint && <span className="text-xs text-[var(--color-muted)]">{hint}</span>}
    </Card>
  );
}

export function ProgressBar({
  value,
  max = 1,
  tone = "primary",
}: {
  value: number;
  max?: number;
  tone?: "primary" | "success" | "warning" | "danger";
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const tones = {
    primary: "bg-[var(--color-primary)]",
    success: "bg-[var(--color-success)]",
    warning: "bg-[var(--color-warning)]",
    danger: "bg-[var(--color-danger)]",
  };
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
      <div
        className={cn("h-full rounded-full transition-all", tones[tone])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-[var(--color-surface-2)]",
        className
      )}
    />
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 text-sm",
        className
      )}
    >
      <span className="text-[var(--color-faint)]">
        {start}–{end} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft size={14} /> Prev
        </Button>
        <span className="tabular-nums text-[var(--color-muted)]">
          {page} / {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          Next <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  );
}
