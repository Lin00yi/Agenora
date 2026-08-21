"use client";

import { ChevronLeft } from "lucide-react";

export const DEFAULT_TITLE = "新对话";

export function ChatTopBar({
  title,
  onOpenSidebar,
}: {
  title: string;
  onOpenSidebar: () => void;
}) {
  return (
    <header
      className="kf-topbar kf-chat-header flex h-14 shrink-0 items-center gap-2 px-3 sm:h-[64px] sm:gap-3 sm:px-4 xl:px-7"
      data-kf-region="topbar"
    >
      <button
        className="kf-mobile-sidebar-action inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg border lg:hidden"
        onClick={onOpenSidebar}
        type="button"
        aria-label="打开侧栏"
      >
        <ChevronLeft className="h-5 w-5 rotate-180" />
      </button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em]">{title}</h1>
      </div>
    </header>
  );
}
