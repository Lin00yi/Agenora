"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Plus,
  MessageSquare,
  Pencil,
  Trash2,
  X,
  Menu,
  BookOpen,
  Settings,
  Sparkles,
  ChevronUp,
  LogOut,
  Shield,
} from "lucide-react";
import Brand from "@/components/Brand";
import SystemSettingsDialog from "@/components/SystemSettingsDialog";
import type { Conversation } from "@/lib/conversationStore";
import type { User } from "@/lib/auth";
import { cn } from "@/lib/cn";

type Props = {
  conversations: Conversation[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  /** v2-M7: optional inline rename. If omitted, the pencil icon is hidden. */
  onRename?: (id: string, newTitle: string) => Promise<void> | void;
  open: boolean;
  onToggle: () => void;
  /** v3-M1: user info for bottom card + logout handler (DeepSeek-style). */
  user: User | null;
  onLogout: () => void;
  /** v3-M5: notify parent when /me payload changes (e.g. display_name edit). */
  onUserChanged?: (u: User) => void;
};

export default function Sidebar({
  conversations,
  currentId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  open,
  onToggle,
  user,
  onLogout,
  onUserChanged,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const commitRename = (id: string, currentTitle: string, value: string) => {
    const v = value.trim();
    setEditingId(null);
    if (!onRename || !v || v === currentTitle) return;
    void onRename(id, v);
  };

  const requestDelete = (id: string, title: string) => {
    if (window.confirm(`删除对话「${title}」？此操作不可恢复。`)) {
      onDelete(id);
    }
  };

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          onClick={onToggle}
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm md:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[18rem] flex-col border-r border-surface-border/70 bg-surface/96 backdrop-blur-xl transition-transform md:relative md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-surface-border/60 px-3">
          <Brand size="sm" />
          <button
            onClick={onToggle}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg hover:bg-surface-2 md:hidden"
            aria-label="关闭侧栏"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* New chat */}
        <button
          onClick={onNew}
          className="mx-3 mt-3 inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-brand/25 bg-brand px-3 text-sm font-medium text-white shadow-soft transition-all hover:bg-brand-dark active:scale-[0.98]"
          type="button"
        >
          <Plus className="h-4 w-4" />
          新对话
        </button>

        {/* Conversation list */}
        <nav className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations.length === 0 ? (
            <div className="mt-4 flex flex-col items-center gap-2 rounded-lg border border-dashed border-surface-border/80 bg-surface-2/45 px-3 py-6 text-center text-xs text-muted">
              <Sparkles className="h-4 w-4 text-brand/70" />
              <div>还没有对话</div>
              <button
                onClick={onNew}
                className="text-brand hover:underline"
                type="button"
              >
                开始第一次对话 →
              </button>
            </div>
          ) : (
            conversations.map((c) => {
              const active = c.id === currentId;
              const isEditing = editingId === c.id;
              return (
                <div
                  key={c.id}
                  className={cn(
                    "group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-all",
                    active
                      ? "bg-brand/12 font-medium text-fg shadow-sm ring-1 ring-brand/20"
                      : "text-fg/80 hover:bg-surface-2"
                  )}
                  onClick={() => !isEditing && onSelect(c.id)}
                >
                  <MessageSquare className="h-3.5 w-3.5 flex-none opacity-60" />
                  {isEditing ? (
                    <input
                      autoFocus
                      defaultValue={c.title}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          commitRename(c.id, c.title, (e.target as HTMLInputElement).value);
                        } else if (e.key === "Escape") {
                          setEditingId(null);
                        }
                      }}
                      onBlur={(e) => commitRename(c.id, c.title, e.target.value)}
                      className="flex-1 min-w-0 bg-transparent outline-none border-b border-brand/50 text-sm"
                      maxLength={128}
                    />
                  ) : (
                    <span className="flex-1 truncate" title={c.title}>
                      {c.title}
                    </span>
                  )}
                  {!isEditing && onRename && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(c.id);
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg opacity-100 transition hover:bg-brand/15 hover:text-brand sm:opacity-0 sm:group-hover:opacity-100"
                      aria-label="重命名对话"
                      title="重命名"
                      type="button"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {!isEditing && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        requestDelete(c.id, c.title);
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg opacity-100 transition hover:bg-danger/15 hover:text-danger sm:opacity-0 sm:group-hover:opacity-100"
                      aria-label="删除对话"
                      title="删除"
                      type="button"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              );
            })
          )}
        </nav>

        {/* v3-M1: bottom user card with popup menu (DeepSeek style) */}
        <UserMenu
          user={user}
          onLogout={onLogout}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      </aside>

      {/* v3-M5: system settings dialog (account / data / about / general) */}
      {user && (
        <SystemSettingsDialog
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          user={user}
          onUserChanged={(u) => onUserChanged?.(u)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// v3-M1: UserMenu — bottom user card with popup menu (DeepSeek-style)
// ---------------------------------------------------------------------------
function UserMenu({
  user,
  onLogout,
  onOpenSettings,
}: {
  user: User | null;
  onLogout: () => void;
  onOpenSettings: () => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // ESC + outside click → close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  if (!user) {
    // Edge case: not signed in (shouldn't happen on the chat page, but
    // keep the layout stable for tests / initial paint).
    return <div className="border-t px-3 py-3 text-xs text-muted">未登录</div>;
  }

  const displayLabel = user.display_name?.trim() || user.email;
  const initial = (user.display_name?.trim()?.[0] || user.email[0] || "?").toUpperCase();

  return (
    <div ref={containerRef} className="relative border-t border-surface-border/70 p-2">
      {/* Popup menu — anchored above the trigger button */}
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-1 overflow-hidden rounded-lg border border-surface-border/80 bg-surface shadow-lift">
          <button
            onClick={() => {
              setOpen(false);
              onOpenSettings();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-fg/90 transition hover:bg-surface-2"
            type="button"
          >
            <Settings className="h-4 w-4 opacity-70" />
            设置
          </button>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm text-fg/90 transition hover:bg-surface-2"
          >
            <Settings className="h-4 w-4 opacity-70" />
            模型设置
          </Link>
          <Link
            href="/kbs"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm text-fg/90 transition hover:bg-surface-2"
          >
            <BookOpen className="h-4 w-4 opacity-70" />
            我的知识库
          </Link>
          {user.is_admin && (
            <Link
              href="/admin"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-fg/90 transition hover:bg-surface-2"
            >
              <Shield className="h-4 w-4 opacity-70" />
              后台管理
            </Link>
          )}
          <div className="border-t" />
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-danger transition hover:bg-danger/10"
            type="button"
          >
            <LogOut className="h-4 w-4" />
            登出
          </button>
        </div>
      )}

      {/* Trigger button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-surface-2",
          open && "bg-surface-2"
        )}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="用户菜单"
      >
        <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-brand/15 text-xs font-semibold text-brand">
          {initial}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm" title={user.email}>
          {displayLabel}
        </span>
        <ChevronUp
          className={cn(
            "h-4 w-4 flex-none text-muted transition-transform",
            !open && "rotate-180"
          )}
        />
      </button>
    </div>
  );
}

export function SidebarToggle({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-surface-2 md:hidden"
      aria-label="打开侧栏"
      type="button"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}
