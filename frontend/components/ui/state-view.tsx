import type { ReactNode } from "react";
import { AlertCircle, FileQuestion, Info, LoaderCircle } from "lucide-react";

import { cn } from "@/lib/cn";

type StateViewProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  density?: "normal" | "compact";
};

/** A single, calm visual language for page-level empty, loading, and error states. */
export function StateView({
  title,
  description,
  action,
  className,
  density = "normal",
  variant = "empty",
}: StateViewProps & { variant?: "empty" | "error" | "notice" }) {
  const Icon = variant === "error" ? AlertCircle : variant === "notice" ? Info : FileQuestion;
  return (
    <section
      className={cn(
        "ak-state-view",
        density === "compact" && "ak-state-view-compact",
        variant === "error" && "ak-state-view-error",
        variant === "notice" && "ak-state-view-notice",
        className
      )}
      role={variant === "error" ? "alert" : undefined}
    >
      <span className="ak-state-icon" aria-hidden>
        <Icon className="size-5" />
      </span>
      {title && <h2 className="text-pretty text-sm font-semibold text-fg">{title}</h2>}
      {description && <p className="max-w-md text-pretty text-sm leading-6 text-muted">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </section>
  );
}

export function LoadingState({
  label = "正在加载",
  description = "正在准备内容，请稍候。",
  className,
  compact = false,
}: {
  label?: string;
  description?: string;
  className?: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div className={cn("ak-inline-loading", className)} role="status" aria-live="polite">
        <LoaderCircle className="size-4 animate-spin text-primary" aria-hidden />
        <span>{label}…</span>
      </div>
    );
  }
  return (
    <section className={cn("ak-loading-state", className)} role="status" aria-live="polite" aria-busy="true">
      <div className="ak-loading-orbit" aria-hidden>
        <LoaderCircle className="size-5 animate-spin text-primary" />
      </div>
      <h2 className="text-sm font-semibold text-fg">{label}</h2>
      <p className="text-sm text-muted">{description}</p>
      <div className="ak-skeleton-lines" aria-hidden>
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

export function PageSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("ak-page-skeleton", className)} role="status" aria-label="正在加载页面" aria-busy="true">
      <div className="ak-skeleton h-5 w-32" />
      <div className="ak-skeleton h-8 w-56" />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="ak-skeleton h-28" />
        <div className="ak-skeleton h-28" />
        <div className="ak-skeleton h-28" />
      </div>
    </div>
  );
}
