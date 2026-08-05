"use client";

import Link from "next/link";
import { ChevronLeft, Copy, Database, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Conversation } from "@/lib/conversationStore";
import { formatTime } from "./utils";

export const DEFAULT_TITLE = "新对话";

export function ChatTopBar({
  title,
  onOpenSidebar,
  conversation = null,
  kbName = "通用对话",
  modelLabel = "-",
  messageStats = "-",
}: {
  title: string;
  onOpenSidebar: () => void;
  conversation?: Conversation | null;
  kbName?: string;
  modelLabel?: string;
  messageStats?: string;
}) {
  return (
    <header
      className="kf-topbar kf-chat-header grid h-[64px] shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 xl:px-7"
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

      <div className="min-w-0">
        <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em]">{title}</h1>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="kf-topbar-menu-trigger inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg border border-transparent text-muted transition hover:border-surface-border/80 hover:bg-surface-2/60 hover:text-ink"
            aria-label="会话信息"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <DropdownMenuLabel>会话信息</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="space-y-2 px-2 py-1.5 text-xs">
            <SessionMetaRow label="会话 ID" value={conversation?.id?.slice(0, 8) ?? "-"} />
            <SessionMetaRow label="创建时间" value={formatTime(conversation?.created_at)} />
            <SessionMetaRow label="最近更新" value={formatTime(conversation?.updated_at)} />
            <SessionMetaRow label="消息统计" value={messageStats} />
            <SessionMetaRow label="知识库" value={kbName} />
            <SessionMetaRow label="模型" value={modelLabel} />
          </div>
          {conversation?.id ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => {
                  void navigator.clipboard.writeText(conversation.id);
                  toast.success("已复制会话 ID");
                }}
              >
                <Copy className="h-3.5 w-3.5" />
                复制完整会话 ID
              </DropdownMenuItem>
              {conversation.kb_id ? (
                <DropdownMenuItem asChild>
                  <Link href={`/kbs/${conversation.kb_id}`}>
                    <Database className="h-3.5 w-3.5" />
                    打开知识库
                  </Link>
                </DropdownMenuItem>
              ) : null}
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

function SessionMetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-muted">{label}</span>
      <span className="min-w-0 truncate text-right text-ink" title={value}>
        {value}
      </span>
    </div>
  );
}
