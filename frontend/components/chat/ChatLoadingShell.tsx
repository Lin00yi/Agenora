"use client";

import Brand from "@/components/Brand";
import { StateView } from "@/components/ui/state-view";
import { cn } from "@/lib/cn";
import { ChatTopBar, DEFAULT_TITLE } from "./ChatTopBar";

export function ChatLoadingShell({
  label,
  description,
  animated = true,
}: {
  label: string;
  description?: string;
  animated?: boolean;
}) {
  return (
    <div
      className={cn(
        "kf-chat kf-chat-root h-full w-full overflow-hidden",
        animated && "kf-page-transition"
      )}
    >      <div className="grid h-full grid-cols-1 lg:grid-cols-[286px_minmax(0,1fr)]">
        <aside
          aria-hidden="true"
          className="kf-sidebar kf-sidebar-shell hidden h-full min-h-0 w-[286px] flex-col overflow-hidden border-r px-3 py-4 lg:flex"
        >
          <div className="kf-sidebar-top px-1 pb-3 pt-1">
            <Brand className="kf-sidebar-brand" size="md" tone="soft" />
            <div className="kf-sidebar-new kf-sidebar-primary-action mt-5 h-[var(--control-h)] rounded-lg border" />
            <div className="kf-sidebar-search mt-4 h-[var(--control-h)] rounded-lg border" />
          </div>
          <div className="kf-sidebar-separator my-4 h-px" />
          <div className="space-y-2 px-1">
            <div className="kf-sidebar-skeleton h-4 w-28 rounded" />
            <div className="kf-sidebar-skeleton h-12 rounded-lg" />
            <div className="kf-sidebar-skeleton h-12 rounded-lg" />
            <div className="kf-sidebar-skeleton h-12 rounded-lg" />
          </div>
          <div className="kf-user-trigger mt-auto h-[58px] rounded-lg border" />
        </aside>

        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          <ChatTopBar title={DEFAULT_TITLE} onOpenSidebar={() => {}} />
          <main className="kf-main kf-workspace flex h-full min-h-0 min-w-0 flex-col">
            <div className="kf-thread relative min-h-0 flex-1">
              <div className="kf-thread-scroll absolute inset-0 overflow-y-auto">
                <div className="kf-thread-inner mx-auto flex min-h-full w-full max-w-[860px] items-center justify-center px-5 pt-5">
                  <StateView
                    variant="loading"
                    title={label}
                    description={description}
                    className="w-full max-w-md"
                  />
                </div>
              </div>
              <div
                aria-hidden="true"
                className="kf-thread-dock pointer-events-none absolute bottom-0 left-0 z-10"
              >
                <div className="kf-composer kf-composer-docked px-5 pb-3 pt-1">
                  <div className="kf-composer-box mx-auto h-[105px] max-w-[860px] rounded-[var(--radius-composer)]" />
                  <div className="kf-composer-skeleton mx-auto mt-2 h-4 w-48 rounded" />
                </div>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}