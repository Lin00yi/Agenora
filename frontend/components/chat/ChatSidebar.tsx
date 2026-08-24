"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  LoaderCircle,
  LogOut,
  MessageCircle,
  MoreHorizontal,
  Pin,
  PanelLeftClose,
  Plus,
  Search,
  Settings,
  Shield,
  Trash2,
} from "lucide-react";
import Brand from "@/components/Brand";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/cn";
import type { User } from "@/lib/auth";
import type { Conversation } from "@/lib/conversationStore";
import { HoverMarqueeTitle } from "./HoverMarqueeTitle";
import {
  loadPinnedConversationIds,
  persistPinnedConversationIds,
  sortConversationsByPin,
  togglePinnedConversationId,
} from "./pinnedConversations";
import { formatConversationTime, getConversationStatusDotClass } from "./utils";

export function ChatSidebar({
  open,
  collapsed,
  conversations,
  conversationTotal,
  conversationHasMore,
  conversationLoadingMore,
  currentId,
  user,
  onClose,
  onToggleCollapsed,
  onNew,
  onSelectConversation,
  onDeleteConversation,
  onLoadMoreConversations,
  onOpenAccountSettings,
  onOpenSearch,
  onLogout,
}: {
  open: boolean;
  collapsed: boolean;
  conversations: Conversation[];
  conversationTotal: number;
  conversationHasMore: boolean;
  conversationLoadingMore: boolean;
  currentId: string | null;
  user: User | null;
  onClose: () => void;
  onToggleCollapsed: () => void;
  onNew: (kbId?: string | null) => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onLoadMoreConversations: () => void;
  onOpenAccountSettings: () => void;
  onOpenSearch: () => void;
  onLogout: () => void;
}) {
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [recentPopoverOpen, setRecentPopoverOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);
  const userMenuRefs = useRef<Array<HTMLDivElement | null>>([]);
  const recentPopoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPinnedIds(loadPinnedConversationIds());
  }, []);

  const filteredConversations = sortConversationsByPin(conversations, pinnedIds);

  const handleTogglePin = useCallback((id: string) => {
    setPinnedIds((prev) => {
      const next = togglePinnedConversationId(prev, id);
      persistPinnedConversationIds(next);
      return next;
    });
  }, []);
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
    if (!userMenuOpen && !recentPopoverOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setUserMenuOpen(false);
      setRecentPopoverOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const inUserMenu = userMenuRefs.current.some((element) => element?.contains(target));
      const inRecentPopover = recentPopoverRef.current?.contains(target);
      if (target.closest?.('[data-slot="select-content"]')) return;
      if (!inUserMenu) setUserMenuOpen(false);
      if (!inRecentPopover) setRecentPopoverOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointerDown);
    };
  }, [recentPopoverOpen, userMenuOpen]);

  return (
    <aside
      className={cn(
        "kf-sidebar kf-sidebar-shell kf-motion-enter fixed inset-y-0 left-0 z-40 flex h-full min-h-0 w-[286px] flex-col overflow-hidden border-r px-3 py-4 shadow-[0_24px_64px_rgba(0,0,0,0.28)] transition-transform duration-surface ease-ui-drawer lg:relative lg:z-auto lg:w-full lg:translate-x-0 lg:shadow-none",
        collapsed && "lg:z-20 lg:overflow-visible lg:px-2",
        open ? "translate-x-0" : "-translate-x-full"
      )}
      data-kf-region="sidebar"
      data-collapsed={collapsed || undefined}
      aria-label="会话侧栏"
    >
      <div className={cn("flex min-h-0 flex-1 flex-col", collapsed && "lg:hidden")}>
      <div className="kf-sidebar-top px-1 pb-3 pt-1">
        <div className="flex items-center justify-between">
          <Brand className="kf-sidebar-brand" size="md" tone="soft" />
          <button
            aria-label="折叠侧栏"
            className="kf-sidebar-toggle kf-press hidden size-[var(--control-h)] items-center justify-center rounded-lg border lg:inline-flex"
            onClick={() => {
              setUserMenuOpen(false);
              onToggleCollapsed();
            }}
            type="button"
            title="折叠侧栏"
          >
            <PanelLeftClose className="size-[18px]" aria-hidden />
          </button>
          <button
            aria-label="收起侧栏"
            className="kf-sidebar-toggle kf-press inline-flex size-[var(--control-h)] items-center justify-center rounded-lg border lg:hidden"
            onClick={onClose}
            type="button"
            title="收起侧栏"
          >
            <PanelLeftClose className="size-[18px]" aria-hidden />
          </button>
        </div>

        <button
          className="kf-sidebar-new kf-sidebar-primary-action kf-press mt-5 flex h-[var(--control-h)] w-full items-center justify-center gap-2 rounded-lg border text-sm font-medium"
          onClick={() => onNew()}
          type="button"
        >
          <Plus className="h-4 w-4" />
          {"\u65b0\u5efa\u5bf9\u8bdd"}
        </button>

        <button
          className="kf-sidebar-search mt-4 flex h-[var(--control-h)] w-full cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm transition hover:bg-[rgb(var(--kf-surface))]"
          onClick={onOpenSearch}
          type="button"
          aria-label="搜索历史对话"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span className="kf-sidebar-search-input min-w-0 flex-1 truncate text-left">搜索对话</span>
          <kbd aria-hidden="true" className="kf-sidebar-kbd rounded border px-1.5 py-0.5 text-[10px]">
            Ctrl K
          </kbd>
        </button>

      </div>

      <div className="kf-sidebar-separator my-4 h-px shrink-0" />

      <div className="flex min-h-0 basis-0 flex-1 flex-col">
        <div className="kf-sidebar-section-label flex shrink-0 items-center justify-between px-2 pb-2 text-sm">
          <span>{"\u6700\u8fd1\u5bf9\u8bdd"}</span>
          <span className="kf-sidebar-count text-xs tabular-nums">
            {filteredConversations.length}/{conversationTotal}
          </span>
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto pr-1"
          onScroll={handleConversationScroll}
        >
          <div className="space-y-0.5">
            {filteredConversations.map((conversation) => (
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                currentId={currentId}
                pinned={pinnedIds.includes(conversation.id)}
                onSelect={() => onSelectConversation(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onDelete={() => setDeleteTarget(conversation)}
              />
            ))}
            {filteredConversations.length === 0 && (
              <div className="kf-sidebar-empty rounded-lg border border-dashed px-3 py-4 text-sm">
                {"\u8fd8\u6ca1\u6709\u5bf9\u8bdd\uff0c\u5148\u95ee\u4e00\u4e2a\u95ee\u9898\u3002"}
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
      </div>

      <div ref={(element) => { userMenuRefs.current[0] = element; }} className="relative mt-3 shrink-0">
        {userMenuOpen && (
          <div className="kf-popover kf-user-popover absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-lg border">
            <Link
              className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
              href="/kbs"
              onClick={() => setUserMenuOpen(false)}
            >
              <BookOpen className="kf-user-menu-icon h-4 w-4" />
              知识库
            </Link>
            <button
              className="kf-user-menu-item flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left text-sm transition"
              onClick={() => {
                setUserMenuOpen(false);
                onOpenAccountSettings();
              }}
              type="button"
            >
              <Settings className="kf-user-menu-icon h-4 w-4" />
              设置
            </button>
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
        </div>
      </div>
      </div>

      <div
        className={cn(
          "hidden min-h-0 flex-1 flex-col items-center",
          collapsed && "lg:flex"
        )}
      >
        <div className="flex flex-col items-center gap-2 pt-1">
          <button
            aria-label="展开侧栏"
            className="kf-sidebar-rail-action kf-press inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg"
            onClick={onToggleCollapsed}
            title="展开侧栏"
            type="button"
          >
            <Brand showWordmark={false} size="sm" />
          </button>
          <div className="kf-sidebar-separator my-1 h-px w-6" />
          <button
            aria-label="新建对话"
            className="kf-sidebar-rail-action inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg"
            onClick={() => onNew()}
            title="新建对话"
            type="button"
          >
            <Plus className="h-4 w-4" aria-hidden />
          </button>
          <button
            aria-label="搜索历史对话"
            className="kf-sidebar-rail-action inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg"
            onClick={onOpenSearch}
            title="搜索对话"
            type="button"
          >
            <Search className="h-4 w-4" aria-hidden />
          </button>
          <div
            ref={recentPopoverRef}
            className="relative"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setRecentPopoverOpen(false);
              }
            }}
            onFocus={() => setRecentPopoverOpen(true)}
            onMouseEnter={() => setRecentPopoverOpen(true)}
            onMouseLeave={() => setRecentPopoverOpen(false)}
          >
            <button
              aria-controls="sidebar-recent-conversations"
              aria-expanded={recentPopoverOpen}
              aria-haspopup="dialog"
              aria-label="最近聊天"
              className="kf-sidebar-rail-action inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg"
              onClick={() => setRecentPopoverOpen((isOpen) => !isOpen)}
              title="最近聊天"
              type="button"
            >
              <MessageCircle className="h-4 w-4" aria-hidden />
            </button>
            {recentPopoverOpen && (
              <div className="absolute left-full top-0 z-50 pl-2">
                <section
                  id="sidebar-recent-conversations"
                  aria-label="最近聊天"
                  className="kf-popover kf-sidebar-recent-popover kf-motion-enter w-56 overflow-hidden rounded-xl border p-1.5"
                  role="dialog"
                >
                  <div className="px-2.5 pb-1.5 pt-1 text-xs font-medium text-[color:var(--chat-muted)]">
                    最近聊天
                  </div>
                  <div className="max-h-[320px] space-y-0.5 overflow-y-auto">
                    {filteredConversations.slice(0, 10).map((conversation) => (
                      <button
                        key={conversation.id}
                        className={cn(
                          "kf-sidebar-recent-item w-full truncate rounded-md px-2.5 py-1.5 text-left text-xs",
                          conversation.id === currentId && "kf-sidebar-recent-item-active"
                        )}
                        onClick={() => {
                          setRecentPopoverOpen(false);
                          onSelectConversation(conversation.id);
                        }}
                        title={conversation.title}
                        type="button"
                      >
                        {conversation.title}
                      </button>
                    ))}
                    {filteredConversations.length === 0 && (
                      <p className="px-2.5 py-3 text-xs text-[color:var(--chat-muted)]">
                        暂无最近会话
                      </p>
                    )}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>

        <div ref={(element) => { userMenuRefs.current[1] = element; }} className="relative mt-auto pb-1">
          {userMenuOpen && (
            <div className="kf-popover kf-user-popover absolute bottom-full left-0 z-50 mb-2 w-56 overflow-hidden rounded-lg border">
              <Link
                className="kf-user-menu-item flex min-h-[var(--control-h)] items-center gap-2 px-3 py-2.5 text-sm transition"
                href="/kbs"
                onClick={() => setUserMenuOpen(false)}
              >
                <BookOpen className="kf-user-menu-icon h-4 w-4" />
                知识库
              </Link>
              <button
                className="kf-user-menu-item flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left text-sm transition"
                onClick={() => {
                  setUserMenuOpen(false);
                  onOpenAccountSettings();
                }}
                type="button"
              >
                <Settings className="kf-user-menu-icon h-4 w-4" />
                设置
              </button>
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
          <button
            aria-expanded={userMenuOpen}
            aria-haspopup="menu"
            aria-label="用户菜单"
            className="kf-sidebar-rail-action inline-flex size-[var(--control-h)] cursor-pointer items-center justify-center rounded-lg"
            onClick={() => setUserMenuOpen((isOpen) => !isOpen)}
            title="用户菜单"
            type="button"
          >
            <span className="kf-user-avatar flex size-7 items-center justify-center rounded-md border text-xs font-semibold shadow-sm">
              {(user?.display_name?.[0] || user?.email?.[0] || "Z").toUpperCase()}
            </span>
          </button>
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

function ConversationRow({
  conversation,
  currentId,
  pinned,
  onSelect,
  onTogglePin,
  onDelete,
}: {
  conversation: Conversation;
  currentId: string | null;
  pinned: boolean;
  onSelect: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const statusDotClass = getConversationStatusDotClass(conversation, currentId);
  const messageCount = conversation.messages.length || conversation.message_count || 0;
  const active = conversation.id === currentId;
  const showActions = hovered || pinned;

  return (
    <div
      className={cn(
        "kf-sidebar-row group flex min-h-10 items-center gap-0.5 rounded-lg border px-2 py-1.5 text-sm transition-[background-color,border-color,color]",
        active ? "kf-sidebar-row-active" : "kf-sidebar-row-idle"
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        className="min-w-0 flex-1 cursor-pointer px-1.5 text-left"
        onClick={onSelect}
        type="button"
        title={conversation.title}
      >
        <HoverMarqueeTitle
          text={conversation.title}
          className="text-[13px] leading-5 text-[color:var(--chat-ink)]"
          scrolling={hovered}
        />
        <span className="kf-sidebar-meta mt-0.5 flex items-center gap-2 text-[11px]">
          <span className={cn("h-1.5 w-1.5 rounded-sm", statusDotClass)} />
          <span>{formatConversationTime(conversation.updated_at)}</span>
          <span className="kf-sidebar-meta-separator h-1 w-1 rounded-sm" />
          <span>
            {messageCount}
            {" \u6761\u6d88\u606f"}
          </span>
        </span>
      </button>
      <div
        className={cn(
          "shrink-0",
          !showActions && "hidden group-focus-within:block"
        )}
      >
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              aria-label={`${conversation.title} 更多操作`}
              className="kf-sidebar-row-action inline-flex size-7 cursor-pointer items-center justify-center rounded-lg"
              onClick={(event) => event.stopPropagation()}
              title="更多操作"
              type="button"
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-36">
            <DropdownMenuItem className="cursor-pointer" onSelect={onTogglePin}>
              <Pin className={cn("h-4 w-4", pinned && "fill-current")} />
              {pinned ? "取消置顶" : "置顶对话"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="cursor-pointer" onSelect={onDelete} variant="destructive">
              <Trash2 className="h-4 w-4" />
              删除会话
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
