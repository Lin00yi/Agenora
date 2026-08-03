"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  Edit3,
  Filter,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import ThemeToggle from "@/components/ThemeToggle";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { LoadingState, StateView } from "@/components/ui/state-view";
import { getToken } from "@/lib/auth";
import {
  deleteMemory,
  listMemories,
  patchMemory,
  type UserMemory,
} from "@/lib/conversations-api";

type StatusFilter = "active" | "superseded" | "deleted" | "expired" | "all";
type TypeFilter = "all" | "explicit" | "preference" | "constraint";
type ScopeFilter = "all" | "personal" | "kb";

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "active", label: "当前有效" },
  { value: "all", label: "全部状态" },
  { value: "superseded", label: "已覆盖" },
  { value: "deleted", label: "已删除" },
  { value: "expired", label: "已过期" },
];

const TYPE_OPTIONS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "全部类型" },
  { value: "explicit", label: "显式" },
  { value: "preference", label: "偏好" },
  { value: "constraint", label: "约束" },
];

const SCOPE_OPTIONS: { value: ScopeFilter; label: string }[] = [
  { value: "all", label: "全部范围" },
  { value: "personal", label: "全局" },
  { value: "kb", label: "知识库" },
];

export default function MemoriesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<UserMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>("active");
  const [type, setType] = useState<TypeFilter>("all");
  const [scope, setScope] = useState<ScopeFilter>("all");
  const [query, setQuery] = useState("");
  const [editTarget, setEditTarget] = useState<UserMemory | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserMemory | null>(null);

  const refresh = async (nextStatus: StatusFilter = status) => {
    setRefreshing(true);
    try {
      const memories = await listMemories({ status: nextStatus });
      setRows(memories);
    } catch (e) {
      toast.error((e as Error).message || "读取记忆失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void refresh(status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((memory) => {
      if (type !== "all" && memory.type !== type) return false;
      if (scope !== "all" && memory.scope !== scope) return false;
      if (!needle) return true;
      return [
        memory.content,
        memory.key ?? "",
        memory.value ?? "",
        memory.type,
        memory.source,
        memory.scope,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [query, rows, scope, type]);

  const stats = useMemo(() => {
    const active = rows.filter((m) => m.status === "active").length;
    const byType = rows.reduce<Record<string, number>>((acc, memory) => {
      acc[memory.type] = (acc[memory.type] ?? 0) + 1;
      return acc;
    }, {});
    return { active, total: rows.length, byType };
  }, [rows]);

  const handleStatusChange = (next: StatusFilter) => {
    setStatus(next);
    void refresh(next);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    try {
      await deleteMemory(deleteTarget.id);
      setRows((current) =>
        status === "all"
          ? current.map((item) =>
              item.id === deleteTarget.id ? { ...item, status: "deleted" } : item
            )
          : current.filter((item) => item.id !== deleteTarget.id)
      );
      setDeleteTarget(null);
      toast.success("记忆已删除，不会再注入后续对话");
    } catch (e) {
      toast.error((e as Error).message || "删除记忆失败");
    } finally {
      setBusyId(null);
    }
  };

  const applyEdit = (updated: UserMemory) => {
    setRows((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setEditTarget(null);
  };

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState
          label="正在读取长期记忆"
          description="正在整理已保存的偏好、约束和显式记忆。"
          className="w-full max-w-md"
        />
      </div>
    );
  }

  return (
    <div className="app-page min-h-dvh text-fg">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-4 sm:px-6">
          <Link
            href="/"
            className="app-nav-link app-nav-link-compact"
          >
            <ArrowLeft className="h-4 w-4" />
            返回对话
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="admin-btn-secondary"
              onClick={() => void refresh(status)}
              disabled={refreshing}
            >
              {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="app-page-content mx-auto max-w-6xl px-4 py-7 sm:px-6 sm:py-10">
        <div className="admin-panel overflow-hidden">
          <div className="border-b border-surface-border/70 bg-surface-2/45 px-5 py-5 sm:px-6">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold tracking-[0.16em] text-brand">
                  记忆治理
                </p>
                <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
                  <span className="admin-icon-tile admin-icon-tile-brand rounded-md">
                    <BrainCircuit className="h-5 w-5" />
                  </span>
                  我的记忆
                </h1>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
                  审计系统从对话中保存的长期记忆，筛选、编辑或删除任意记录；只有有效记忆会参与后续上下文注入。
                </p>
              </div>

              <div className="grid grid-cols-3 gap-2 rounded-lg border border-surface-border/80 bg-surface p-2 text-center shadow-sm">
                <Stat label="当前有效" value={stats.active} />
                <Stat label="本页记录" value={stats.total} />
                <Stat label="有向量" value={rows.filter((m) => m.has_embedding).length} />
              </div>
            </div>
          </div>

          <section className="border-b border-surface-border/70 bg-surface px-5 py-4 sm:px-6">
            <div className="grid gap-3 md:grid-cols-[minmax(16rem,1fr)_repeat(3,minmax(0,9.5rem))]">
              <label className="relative block md:col-span-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索内容、键、值或来源"
                  className="pl-9"
                  aria-label="搜索记忆"
                />
              </label>
              <Select
                value={status}
                onChange={(e) => handleStatusChange(e.target.value as StatusFilter)}
                options={STATUS_OPTIONS}
                aria-label="按状态筛选"
              />
              <Select
                value={type}
                onChange={(e) => setType(e.target.value as TypeFilter)}
                options={TYPE_OPTIONS}
                aria-label="按类型筛选"
              />
              <Select
                value={scope}
                onChange={(e) => setScope(e.target.value as ScopeFilter)}
                options={SCOPE_OPTIONS}
                aria-label="按范围筛选"
              />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span className="inline-flex items-center gap-1.5 rounded-md border border-surface-border/70 bg-surface-2 px-2.5 py-1 font-medium text-fg">
                <Filter className="h-3.5 w-3.5 text-brand" />
                类型分布
              </span>
              {(stats.byType.preference ?? 0) > 0 && (
                <span className="chip">偏好 {stats.byType.preference}</span>
              )}
              {(stats.byType.constraint ?? 0) > 0 && (
                <span className="chip">约束 {stats.byType.constraint}</span>
              )}
              {(stats.byType.explicit ?? 0) > 0 && (
                <span className="chip">显式 {stats.byType.explicit}</span>
              )}
              {(stats.byType.preference ?? 0) === 0 &&
                (stats.byType.constraint ?? 0) === 0 &&
                (stats.byType.explicit ?? 0) === 0 && (
                  <span className="text-muted">暂无分类数据</span>
                )}
            </div>
          </section>

          <section className="bg-surface-2/35 p-3 sm:p-4">
            {filtered.length === 0 ? (
              <StateView
                title="没有匹配的记忆"
                description="换一个筛选条件，或继续对话让系统在高置信度场景下自动保存。"
                className="border-surface-border bg-surface"
              />
            ) : (
              <div className="space-y-2.5">
                {filtered.map((memory) => (
                  <MemoryRow
                    key={memory.id}
                    memory={memory}
                    busy={busyId === memory.id}
                    onEdit={() => setEditTarget(memory)}
                    onDelete={() => setDeleteTarget(memory)}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </main>

      <MemoryEditDialog
        memory={editTarget}
        busy={busyId === editTarget?.id}
        onClose={() => {
          if (!busyId) setEditTarget(null);
        }}
        onSaving={(id) => setBusyId(id)}
        onSaved={applyEdit}
        onDone={() => setBusyId(null)}
      />

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !busyId) setDeleteTarget(null);
        }}
        title="删除这条记忆？"
        description="删除后，它不会再作为长期记忆注入后续对话。该操作会保留审计状态。"
        confirmLabel="删除"
        variant="danger"
        busy={deleteTarget !== null && busyId === deleteTarget.id}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 rounded-md px-3 py-2">
      <div className="text-lg font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="truncate text-xs text-muted">{label}</div>
    </div>
  );
}

function MemoryRow({
  memory,
  busy,
  onEdit,
  onDelete,
}: {
  memory: UserMemory;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <article className="group rounded-lg border border-surface-border/80 bg-surface shadow-sm transition-[background-color,border-color,box-shadow] duration-200 hover:border-brand/30 hover:bg-surface/95 hover:shadow-[0_10px_28px_rgb(15_23_42/0.08)]">
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_17rem_auto]">
        <div className="min-w-0 border-b border-surface-border/55 p-4 lg:border-b-0 lg:border-r lg:border-surface-border/65">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={memory.status === "active" ? "default" : "outline"}>
              {statusLabel(memory.status)}
            </Badge>
            <Badge variant="secondary">{memoryTypeLabel(memory.type)}</Badge>
            <Badge variant="outline">{memory.scope === "kb" ? "知识库范围" : "全局范围"}</Badge>
            {memory.has_embedding ? (
              <span className="inline-flex min-h-6 items-center gap-1 rounded-md border border-brand/15 bg-brand/5 px-2 text-xs font-medium text-muted">
                <CheckCircle2 className="h-3.5 w-3.5 text-brand" />
                已向量化
              </span>
            ) : null}
          </div>
          <p className="break-words text-sm font-medium leading-relaxed">{memory.content}</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
            <MetaPill label="来源" value={memorySourceLabel(memory.source)} />
            <MetaPill label="重要度" value={memory.importance.toFixed(2)} />
            <MetaPill label="置信度" value={`${Math.round(memory.confidence * 100)}%`} />
          </div>
        </div>
        <div className="grid gap-2 border-b border-surface-border/55 bg-surface-2/45 p-4 text-xs text-muted lg:border-b-0 lg:border-r lg:border-surface-border/65">
          <div className="min-w-0">
            <div className="mb-1 font-medium text-fg">结构键</div>
            <div className="truncate">{memory.key || "-"}</div>
          </div>
          <div className="min-w-0">
            <div className="mb-1 font-medium text-fg">结构值</div>
            <div className="truncate">{memory.value || "-"}</div>
          </div>
          <div className="flex min-w-0 items-center gap-1.5 rounded-md border border-surface-border/55 bg-surface px-2.5 py-1.5 shadow-sm">
            <CalendarClock className="h-3.5 w-3.5 text-brand" />
            <span className="truncate">{formatMemoryDate(memory.updated_at)}</span>
          </div>
          <div className="truncate rounded-md border border-surface-border/55 bg-surface px-2.5 py-1.5 shadow-sm">
            {memory.expires_at ? `到期：${formatMemoryDate(memory.expires_at)}` : "长期有效"}
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-end gap-2 bg-surface p-3 lg:flex-col lg:justify-center lg:bg-surface-2/25">
          <button
            type="button"
            className="admin-icon-action admin-icon-action-lg admin-icon-action-brand"
            onClick={onEdit}
            disabled={busy}
            aria-label="编辑记忆"
            title="编辑记忆"
          >
            <Edit3 className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="admin-icon-action admin-icon-action-lg admin-icon-action-danger"
            onClick={onDelete}
            disabled={busy || memory.status === "deleted"}
            aria-label="删除记忆"
            title="删除记忆"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </article>
  );
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-1 rounded-md border border-surface-border/70 bg-surface-2 px-2.5 py-1 shadow-[inset_0_1px_0_rgb(255_255_255/0.35)] dark:shadow-none">
      <span className="text-muted">{label}</span>
      <span className="font-medium text-fg">{value}</span>
    </span>
  );
}

function MemoryEditDialog({
  memory,
  busy,
  onClose,
  onSaving,
  onSaved,
  onDone,
}: {
  memory: UserMemory | null;
  busy: boolean;
  onClose: () => void;
  onSaving: (id: string) => void;
  onSaved: (memory: UserMemory) => void;
  onDone: () => void;
}) {
  const [content, setContent] = useState("");
  const [value, setValue] = useState("");
  const [importance, setImportance] = useState(0.5);
  const [status, setStatus] = useState<"active" | "deleted">("active");

  useEffect(() => {
    if (!memory) return;
    setContent(memory.content);
    setValue(memory.value ?? "");
    setImportance(memory.importance);
    setStatus(memory.status === "deleted" ? "deleted" : "active");
  }, [memory]);

  const save = async () => {
    if (!memory) return;
    const nextContent = content.trim();
    if (nextContent.length < 4) {
      toast.error("记忆内容至少需要 4 个字符");
      return;
    }
    onSaving(memory.id);
    try {
      const updated = await patchMemory(memory.id, {
        content: nextContent,
        value: value.trim() || undefined,
        importance,
        status,
      });
      toast.success("记忆已更新");
      onSaved(updated);
    } catch (e) {
      toast.error((e as Error).message || "更新记忆失败");
    } finally {
      onDone();
    }
  };

  return (
    <Dialog
      open={memory !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="编辑记忆"
      hideFooter
      busy={busy}
      onConfirm={save}
    >
      <div className="space-y-4">
        <label className="block">
          <div className="mb-1 text-xs font-medium text-muted">内容</div>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            maxLength={500}
            disabled={busy}
          />
        </label>
        <label className="block">
          <div className="mb-1 text-xs font-medium text-muted">结构值</div>
          <Input value={value} onChange={(e) => setValue(e.target.value)} maxLength={500} disabled={busy} />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <div className="mb-1 text-xs font-medium text-muted">重要度 {importance.toFixed(2)}</div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={importance}
              onChange={(e) => setImportance(Number(e.target.value))}
              disabled={busy}
              className="h-8 w-full accent-brand"
            />
          </label>
          <label className="block">
            <div className="mb-1 text-xs font-medium text-muted">状态</div>
            <Select
              value={status}
              onChange={(e) => setStatus(e.target.value as "active" | "deleted")}
              disabled={busy}
              options={[
                { value: "active", label: "有效" },
                { value: "deleted", label: "删除" },
              ]}
            />
          </label>
        </div>
        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          <button type="button" className="admin-btn-secondary" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button type="button" className="admin-btn-primary" onClick={save} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            保存
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function memoryTypeLabel(type: UserMemory["type"]) {
  if (type === "preference") return "偏好";
  if (type === "constraint") return "约束";
  if (type === "explicit") return "显式";
  return type;
}

function memorySourceLabel(source: UserMemory["source"]) {
  if (source === "auto_rule") return "自动提取";
  if (source === "user_edited") return "用户编辑";
  if (source === "explicit") return "用户明确要求";
  return source;
}

function statusLabel(status: UserMemory["status"]) {
  if (status === "active") return "有效";
  if (status === "superseded") return "已覆盖";
  if (status === "deleted") return "已删除";
  if (status === "expired") return "已过期";
  return status;
}

function formatMemoryDate(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}
