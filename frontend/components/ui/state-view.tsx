import type { ReactNode } from "react";
import { AlertCircle, FileQuestion, Info, LoaderCircle, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

type StateViewProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  density?: "normal" | "compact";
  variant?: "empty" | "error" | "notice";
  icon?: LucideIcon;
};

/** Shared empty / error / notice surface used in pages and admin panels. */
export function StateView({
  title,
  description,
  action,
  className,
  density = "normal",
  variant = "empty",
  icon,
}: StateViewProps) {
  const Icon =
    icon ?? (variant === "error" ? AlertCircle : variant === "notice" ? Info : FileQuestion);
  const isNoticeBanner = variant === "notice" && density === "compact";

  return (
    <section
      className={cn(
        "kf-state-view",
        density === "compact" && "kf-state-view-compact",
        variant === "error" && "kf-state-view-error",
        variant === "notice" && "kf-state-view-notice",
        isNoticeBanner && "kf-state-view-banner",
        className
      )}
      role={variant === "error" ? "alert" : undefined}
    >
      <span className="kf-state-icon" aria-hidden>
        <Icon className="size-4" />
      </span>
      <div className={cn("min-w-0", !isNoticeBanner && "flex flex-col items-center")}>
        {title ? (
          <h2 className="text-pretty text-sm font-semibold text-ink">{title}</h2>
        ) : null}
        {description ? (
          <p
            className={cn(
              "max-w-md text-pretty text-muted",
              density === "compact" ? "mt-1 text-xs leading-5" : "mt-1.5 text-sm leading-6"
            )}
          >
            {description}
          </p>
        ) : null}
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
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
      <div className={cn("kf-inline-loading", className)} role="status" aria-live="polite">
        <LoaderCircle className="size-4 animate-spin text-brand" aria-hidden />
        <span>{label}…</span>
      </div>
    );
  }
  return (
    <section className={cn("kf-loading-state", className)} role="status" aria-live="polite" aria-busy="true">
      <div className="kf-loading-orbit" aria-hidden>
        <LoaderCircle className="size-5 animate-spin text-brand" />
      </div>
      <h2 className="text-sm font-semibold text-ink">{label}</h2>
      <p className="text-xs leading-5 text-muted">{description}</p>
      <div className="kf-skeleton-lines" aria-hidden>
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

export function PageSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("kf-page-skeleton", className)} role="status" aria-label="正在加载页面" aria-busy="true">
      <div className="kf-skeleton h-5 w-32" />
      <div className="kf-skeleton h-8 w-56" />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="kf-skeleton h-28" />
        <div className="kf-skeleton h-28" />
        <div className="kf-skeleton h-28" />
      </div>
    </div>
  );
}
