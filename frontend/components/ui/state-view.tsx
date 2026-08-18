import { AlertCircle, FileQuestion, Info, LoaderCircle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type StateViewProps = {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  density?: "normal" | "compact";
  variant?: "empty" | "error" | "notice" | "loading";
  icon?: LucideIcon;
  overlay?: boolean;
};

/** Shared empty / loading / error / notice surface used in pages and admin panels. */
export function StateView({
  title,
  description,
  action,
  className,
  density = "normal",
  variant = "empty",
  icon,
  overlay = false,
}: StateViewProps) {
  const isLoading = variant === "loading";
  const isNoticeBanner = variant === "notice" && density === "compact" && !overlay;
  const Icon =
    icon ??
    (isLoading ? LoaderCircle : variant === "error" ? AlertCircle : variant === "notice" ? Info : FileQuestion);
  const resolvedTitle =
    title ?? (isLoading ? (overlay ? "正在刷新" : "正在加载") : undefined);
  const resolvedDescription =
    description ?? (isLoading && !overlay ? "正在准备内容，请稍候。" : undefined);

  return (
    <section
      className={cn(
        "kf-state-view",
        density === "compact" && "kf-state-view-compact",
        variant === "error" && "kf-state-view-error",
        variant === "notice" && "kf-state-view-notice",
        isLoading && "kf-state-view-loading",
        isNoticeBanner && "kf-state-view-banner",
        overlay && "kf-state-view-overlay",
        className
      )}
      role={variant === "error" ? "alert" : isLoading ? "status" : undefined}
      aria-live={isLoading ? "polite" : undefined}
      aria-busy={isLoading || undefined}
    >
      <span className="kf-state-icon" aria-hidden>
        <Icon className={cn("size-4", isLoading && "animate-spin")} />
      </span>
      <div className={cn("min-w-0", !isNoticeBanner && "flex flex-col items-center")}>
        {resolvedTitle ? (
          <h2 className="text-pretty text-sm font-semibold text-ink">{resolvedTitle}</h2>
        ) : null}
        {resolvedDescription ? (
          <p
            className={cn(
              "max-w-md text-pretty text-muted",
              density === "compact" || overlay ? "mt-1 text-xs leading-5" : "mt-1.5 text-sm leading-6"
            )}
          >
            {resolvedDescription}
          </p>
        ) : null}
        {action ? <div className="mt-3">{action}</div> : null}
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
