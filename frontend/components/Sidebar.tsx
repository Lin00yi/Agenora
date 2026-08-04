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
  BrainCircuit,
} from "lucide-react";
import Brand from "@/components/Brand";
import Dialog from "@/components/Dialog";
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
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);

  const commitRename = (id: string, currentTitle: string, value: string) => {
    const v = value.trim();
    setEditingId(null);
    if (!onRename || !v || v === currentTitle) return;
    void onRename(id, v);
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    onDelete(deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          onClick={onToggle}
          className="app-modal-overlay fixed inset-0 z-30 md:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[18rem] flex-col border-r border-surface-border/80 bg-surface/96 shadow-[8px_0_28px_rgb(15_23_42/0.08)] backdrop-blur-xl transition-transform md:relative md:translate-x-0 md:shadow-none",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-surface-border/60 px-3">
          <Brand size="sm" />
          <button
            onClick={onToggle}
            className="admin-icon-action md:hidden"
            aria-label="关闭侧栏"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* New chat */}
        <button
          onClick={onNew}
          className="admin-btn-primary mx-3 mt-3 h-10 px-3"
          type="button"
        >
          <Plus className="h-4 w-4" />
          新对话
        </button>

        {/* Conversation list */}
        <nav className="flex-1 overflow-y-auto px-2 pb-3 pt-3">
          {conversations.length === 0 ? (
            <div className="mt-1 flex flex-col items-center gap-2 rounded-lg border border-dashed border-surface-border/80 bg-surface-2/55 px-3 py-6 text-center text-xs text-muted">
              <Sparkles className="h-4 w-4 text-brand/70" />
              <div>还没有对话</div>
              <button
                onClick={onNew}
                className="inline-flex min-h-[36px] cursor-pointer items-center justify-center rounded-md border border-brand/20 bg-brand/5 px-3 font-medium text-brand transition-colors hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
                type="button"
              >
                开始第一次对话
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
                    "group flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg border border-transparent px-2.5 py-1.5 text-sm transition-[background-color,border-color,color,box-shadow] duration-200 ease-ui-out focus-within:border-brand/30 focus-within:ring-2 focus-within:ring-brand/15",
                    active
                      ? "border-brand/25 bg-brand/10 font-medium text-fg shadow-sm"
                      : "text-muted hover:border-surface-border/80 hover:bg-surface-2 hover:text-fg"
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
                      className="h-[36px] min-w-0 flex-1 rounded-md border border-brand/25 bg-surface px-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
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
                      className="admin-icon-action admin-icon-action-brand admin-icon-action-soft"
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
                        setDeleteTarget(c);
                      }}
                      className="admin-icon-action admin-icon-action-danger admin-icon-action-soft"
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
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null);
        }}
        title={`删除对话「${deleteTarget?.title ?? ""}」？`}
        description="此操作不可恢复。"
        confirmLabel="删除"
        variant="danger"
        onConfirm={confirmDelete}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// v3-M1: UserMenu - bottom user card with popup menu (DeepSeek-style)
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

  // ESC + outside click - close
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
    return <div className="border-t border-surface-border/70 bg-surface-2/35 px-3 py-3 text-xs text-muted">未登录</div>;
  }

  const displayLabel = user.display_name?.trim() || user.email;
  const initial = (user.display_name?.trim()?.[0] || user.email[0] || "?").toUpperCase();

  return (
    <div ref={containerRef} className="relative border-t border-surface-border/70 bg-surface-2/35 p-2">
      {/* Popup menu - anchored above the trigger button */}
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-2 overflow-hidden rounded-lg border border-surface-border/80 bg-surface p-1 shadow-[0_18px_44px_rgb(15_23_42/0.14)]">
          <button
            onClick={() => {
              setOpen(false);
              onOpenSettings();
            }}
            className="flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 rounded-md px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
            type="button"
          >
            <Settings className="h-4 w-4 text-muted" />
            设置
          </button>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex min-h-[var(--control-h)] items-center gap-2 rounded-md px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <Settings className="h-4 w-4 text-muted" />
            模型设置
          </Link>
          <Link
            href="/kbs"
            onClick={() => setOpen(false)}
            className="flex min-h-[var(--control-h)] items-center gap-2 rounded-md px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <BookOpen className="h-4 w-4 text-muted" />
            我的知识库
          </Link>
          <Link
            href="/memories"
            onClick={() => setOpen(false)}
            className="flex min-h-[var(--control-h)] items-center gap-2 rounded-md px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <BrainCircuit className="h-4 w-4 text-muted" />
            我的记忆
          </Link>
          {user.is_admin && (
            <Link
              href="/admin"
              onClick={() => setOpen(false)}
              className="flex min-h-[var(--control-h)] items-center gap-2 rounded-md px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
            >
              <Shield className="h-4 w-4 text-muted" />
              后台管理
            </Link>
          )}
          <div className="my-1 border-t border-surface-border/70" />
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex min-h-[var(--control-h)] w-full cursor-pointer items-center gap-2 rounded-md px-3 text-sm font-medium text-danger transition-colors hover:bg-danger/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/25"
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
          "flex min-h-[48px] w-full cursor-pointer items-center gap-2 rounded-lg border border-transparent px-2.5 py-2 text-left transition-[background-color,border-color,box-shadow] duration-200 hover:border-surface-border/80 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
          open && "border-surface-border/80 bg-surface shadow-sm"
        )}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="用户菜单"
      >
        <span className="admin-icon-tile admin-icon-tile-brand flex-none rounded-md text-xs font-semibold">
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
      className="admin-icon-action border-transparent md:hidden"
      aria-label="打开侧栏"
      type="button"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}
