import { cn } from "@/lib/cn";

/** Structural placeholder shared by settings modules while their data loads. */
export function SettingsModuleSkeleton({
  className,
  rows = 3,
}: {
  className?: string;
  rows?: number;
}) {
  return (
    <div
      className={cn("space-y-5 px-5 py-5 sm:px-6", className)}
      role="status"
      aria-label="正在读取设置"
      aria-busy="true"
    >
      <div className="space-y-2">
        <div className="kf-skeleton h-5 w-36" />
        <div className="kf-skeleton h-4 w-full max-w-xl" />
      </div>
      <div className="space-y-3 rounded-xl border border-surface-border/70 bg-surface p-4 sm:p-5">
        <div className="kf-skeleton h-4 w-28" />
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="space-y-2">
            <div className="kf-skeleton h-3 w-20" />
            <div className="kf-skeleton h-10 w-full" />
          </div>
        ))}
      </div>
      <span className="sr-only">正在准备设置内容</span>
    </div>
  );
}
