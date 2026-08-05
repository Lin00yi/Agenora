"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  ChevronDown,
  LoaderCircle,
  LogOut,
  Plus,
  Search,
  Settings,
  Shield,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import Brand from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { cn } from "@/lib/cn";
import type { User } from "@/lib/auth";
import type { Conversation } from "@/lib/conversationStore";
import { formatConversationTime, getConversationStatusView } from "./utils";

export function ChatSidebar({
  open,
  conversations,
  conversationTotal,
  conversationHasMore,
  conversationLoadingMore,
  currentId,
  currentKbId,
  user,
  busy,
  onClose,
  onNew,
  onSelectConversation,
  onDeleteConversation,
  onLoadMoreConversations,
  onOpenAccountSettings,
  onLogout,
}: {
  open: boolean;
  conversations: Conversation[];
  conversationTotal: number;
  conversationHasMore: boolean;
  conversationLoadingMore: boolean;
  currentId: string | null;
  currentKbId: string | null;
  user: User | null;
  busy: boolean;
  onClose: () => void;
  onNew: (kbId?: string | null) => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onLoadMoreConversations: () => void;
  onOpenAccountSettings: () => void;
  onLogout: () => void;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);
  const filteredConversations = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(searchTerm.trim().toLowerCase())
  );
  const handleConversationScroll = useCallback(
    (event: { currentTarget: HTMLDivElement }) => {
      const target = event.currentTarget;
      const nearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 80;
      if (nearBottom && conversationHasMore && !conversationLoadingMore) {
        onLoadMoreConversations();
      }
    },
    [conversationHasMore, conversationLoadingMore, onLoadMoreConversations]
  );

  useEffect(() => {
    if (!userMenuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUserMenuOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (userMenuRef.current?.contains(target)) return;
      if (target.closest?.('[data-slot="select-content"]')) return;
      setUserMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointerDown);
    };
  }, [userMenuOpen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <aside
      className={cn(
        "kf-sidebar kf-sidebar-shell kf-motion-enter fixed inset-y-0 left-0 z-40 flex h-full min-h-0 w-[286px] flex-col overflow-hidden border-r px-3 py-4 shadow-[0_24px_64px_rgba(0,0,0,0.28)] transition-transform duration-surface ease-ui-drawer lg:relative lg:z-auto lg:translate-x-0 lg:shadow-none",
        open ? "translate-x-0" : "-translate-x-full"
      )}
      data-kf-region="sidebar"
      aria-label="会话侧栏"
    >
      <div className="kf-sidebar-top px-1 pb-3 pt-1">
        <div className="flex items-center justify-between">
          <Brand className="kf-sidebar-brand" size="md" tone="soft" />
          <button
            aria-label="关闭侧栏"
            className="kf-sidebar-icon-action kf-press inline-flex size-[var(--control-h)] items-center justify-center rounded-lg border lg:hidden"
            onClick={onClose}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <button
          className="kf-sidebar-new kf-sidebar-primary-action kf-press mt-5 flex h-[var(--control-h)] w-full items-center justify-center gap-2 rounded-lg border text-sm font-medium"
          onClick={() => onNew(currentKbId)}
          type="button"
        >
          <Plus className="h-4 w-4" />
          {"\u65b0\u5efa\u5bf9\u8bdd"}
        </button>

        <div className="kf-sidebar-search mt-4 flex h-[var(--control-h)] items-center gap-2 rounded-lg border px-3 text-sm">
          <Search className="h-4 w-4" />
          <input
            className="kf-sidebar-search-input min-w-0 flex-1 bg-transparent text-sm outline-none"
            ref={searchInputRef}
            aria-label="搜索历史对话"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="搜索对话"
          />
          <kbd aria-hidden="true" className="kf-sidebar-kbd rounded border px-1.5 py-0.5 text-[10px]">
            Ctrl K
          </kbd>
        </div>

      </div>

      <div className="kf-sidebar-separator my-4 h-px" />

      <div
        className="min-h-0 basis-0 flex-1 overflow-y-auto pr-1"
        onScroll={handleConversationScroll}
      >
        <div className="kf-sidebar-section-label flex items-center justify-between px-2 pb-2 text-sm">
          <span>{"\u6700\u8fd1\u5bf9\u8bdd"}</span>
          <span className="kf-sidebar-count text-xs tabular-nums">
            {filteredConversations.length}/{conversationTotal}
          </span>
        </div>
        <div className="space-y-1">
          {filteredConversations.map((conversation) => {
            const statusView = getConversationStatusView(conversation, currentId, busy);
            const messageCount = conversation.messages.length || conversation.message_count || 0;
            const showStatusTag = conversation.id === currentId && busy;
            return (
            <div
              key={conversation.id}
              className={cn(
                "kf-sidebar-row group flex min-h-12 items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-[background-color,border-color,color]",
                conversation.id === currentId
                  ? "kf-sidebar-row-active"
                  : "kf-sidebar-row-idle"
              )}
            >
              <button
                className="min-w-0 flex-1 cursor-pointer text-left"
                onClick={() => onSelectConversation(conversation.id)}
                type="button"
                title={conversation.title}
              >
                <span className="block truncate">{conversation.title}</span>
                <span className="kf-sidebar-meta mt-0.5 flex items-center gap-2 text-[11px]">
                  <span className={cn("h-1.5 w-1.5 rounded-sm", statusView.dot)} />
                  <span>{formatConversationTime(conversation.updated_at)}</span>
                  <span className="kf-sidebar-meta-separator h-1 w-1 rounded-sm" />
                  <span>{messageCount}{" \u6761\u6d88\u606f"}</span>
                </span>
              </button>
              {showStatusTag && (
                <span
                  className={cn(
                    "kf-sidebar-status-badge shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] group-hover:hidden",
                    statusView.tone
                  )}
                >
                  {statusView.label}
                </span>
              )}
              <button
                aria-label="删除会话"
                className="kf-sidebar-row-action hidden size-8 shrink-0 cursor-pointer items-center justify-center rounded-md group-hover:flex"
                onClick={() => {
                  setDeleteTarget(conversation);
                }}
                type="button"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            );
          })}
          {filteredConversations.length === 0 && (
            <div className="kf-sidebar-empty rounded-lg border border-dashed px-3 py-4 text-sm">
              {searchTerm ? "\u6ca1\u6709\u5339\u914d\u7684\u5bf9\u8bdd\u3002" : "\u8fd8\u6ca1\u6709\u5bf9\u8bdd\uff0c\u5148\u95ee\u4e00\u4e2a\u95ee\u9898\u3002"}
            </div>
          )}
          {(conversationHasMore || conversationLoadingMore) && (
            <button
              className="kf-sidebar-load-more flex min-h-[var(--control-h)] w-full cursor-pointer items-center justify-center gap-2 rounded-lg border text-xs transition disabled:cursor-wait disabled:opacity-70"
              disabled={conversationLoadingMore}
              onClick={onLoadMoreConversations}
              type="button"
            >
              {conversationLoadingMore ? (
                <>
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  {"\u6b63\u5728\u52a0\u8f7d"}
                </>
              ) : (
                "\u52a0\u8f7d\u66f4\u591a\u5bf9\u8bdd"
              )}
            </button>
          )}
        </div>
      </div>

      <div ref={userMenuRef} className="relative mt-3 shrink-0">
        {userMenuOpen && (
          <div className="kf-popover kf-user-popover absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-lg border">
            <button
              className="kf-user-menu-item flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left text-sm transition"
              onClick={() => {
                setUserMenuOpen(false);
                onOpenAccountSettings();
              }}
              type="button"
            >
              <Settings className="kf-user-menu-icon h-4 w-4" />
              账号设置
            </button>
            <Link
              className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
              href="/settings"
              onClick={() => setUserMenuOpen(false)}
            >
              <SlidersHorizontal className="kf-user-menu-icon h-4 w-4" />
              模型设置
            </Link>
            <Link
              className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
              href="/kbs"
              onClick={() => setUserMenuOpen(false)}
            >
              <BookOpen className="kf-user-menu-icon h-4 w-4" />
              我的知识库
            </Link>
            <Link
              className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
              href="/memories"
              onClick={() => setUserMenuOpen(false)}
            >
              <BrainCircuit className="kf-user-menu-icon h-4 w-4" />
              记忆系统
            </Link>
            {user?.is_admin && (
              <Link
                className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
                href="/admin"
                onClick={() => setUserMenuOpen(false)}
              >
                <Shield className="kf-user-menu-icon h-4 w-4" />
                后台管理
              </Link>
            )}
            <div className="kf-sidebar-separator h-px" />
            <button
              className="kf-user-menu-item-danger flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left text-sm transition"
              onClick={() => {
                setUserMenuOpen(false);
                onLogout();
              }}
              type="button"
            >
              <LogOut className="h-4 w-4" />
              退出登录
            </button>
          </div>
        )}
        <div
          className={cn(
            "kf-user-trigger flex min-h-[52px] w-full items-center gap-1.5 rounded-lg border p-1.5 transition",
            userMenuOpen && "kf-user-trigger-open"
          )}
        >
          <button
            aria-expanded={userMenuOpen}
            aria-haspopup="menu"
            aria-label="用户菜单"
            className="flex min-h-[var(--control-h)] min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 rounded-md px-0.5 text-left transition"
            onClick={() => setUserMenuOpen((open) => !open)}
            type="button"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="kf-user-avatar flex size-[var(--control-h)] shrink-0 items-center justify-center rounded-lg border text-sm font-semibold shadow-sm">
                {(user?.display_name?.[0] || user?.email?.[0] || "Z").toUpperCase()}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-[color:var(--chat-ink)]">
                  {user?.display_name || user?.email || "\u7528\u6237"}
                </span>
                <span className="kf-user-role block text-xs">{user?.is_admin ? "\u7ba1\u7406\u5458" : "\u6210\u5458"}</span>
              </span>
            </span>
            <ChevronDown className={cn("kf-user-chevron h-4 w-4 shrink-0 transition", userMenuOpen && "rotate-180")} />
          </button>
          <ThemeToggle compact />
        </div>
      </div>
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null);
        }}
        title={`删除对话「${deleteTarget?.title ?? ""}」？`}
        description="此操作不可恢复。"
        confirmLabel="删除"
        variant="danger"
        onConfirm={() => {
          if (!deleteTarget) return;
          onDeleteConversation(deleteTarget.id);
          setDeleteTarget(null);
        }}
      />
    </aside>
  );
}
