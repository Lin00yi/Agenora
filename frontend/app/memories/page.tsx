"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BrainCircuit,
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
import { Button } from "@/components/ui/button";
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
            className="inline-flex items-center gap-1 text-sm text-muted transition hover:text-fg"
          >
            <ArrowLeft className="h-4 w-4" />
            返回对话
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void refresh(status)}
              disabled={refreshing}
            >
              {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw />}
              刷新
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="app-page-content mx-auto max-w-5xl px-4 py-7 sm:px-6 sm:py-10">
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand">
              Memory control
            </p>
            <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <BrainCircuit className="h-5 w-5 text-brand" />
              我的记忆
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
              这里展示系统从对话中保存的长期记忆。你可以审计、筛选、编辑或删除任意一条；只有有效记忆会参与后续上下文注入。
            </p>
          </div>

          <div className="grid grid-cols-3 gap-2 rounded-lg border border-surface-border bg-surface p-2 text-center">
            <Stat label="当前有效" value={stats.active} />
            <Stat label="本页记录" value={stats.total} />
            <Stat label="有向量" value={rows.filter((m) => m.has_embedding).length} />
          </div>
        </div>

        <section className="mt-7 rounded-lg border border-surface-border bg-surface p-3">
          <div className="grid gap-3 md:grid-cols-[1fr_10rem_10rem_10rem]">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索内容、键、值或来源"
                className="pl-8"
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
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
            <Filter className="h-4 w-4" />
            <span>偏好 {stats.byType.preference ?? 0}</span>
            <span>约束 {stats.byType.constraint ?? 0}</span>
            <span>显式 {stats.byType.explicit ?? 0}</span>
          </div>
        </section>

        <section className="mt-5">
          {filtered.length === 0 ? (
            <StateView
              title="没有匹配的记忆"
              description="换一个筛选条件，或继续对话让系统在高置信度场景下自动保存。"
              className="bg-surface/60"
            />
          ) : (
            <div className="space-y-3">
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
    <div className="min-w-0 px-2 py-1">
      <div className="text-base font-semibold tabular-nums">{value}</div>
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
    <article className="rounded-lg border border-surface-border bg-surface p-4 transition-colors hover:border-brand/30">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant={memory.status === "active" ? "default" : "outline"}>
              {statusLabel(memory.status)}
            </Badge>
            <Badge variant="secondary">{memoryTypeLabel(memory.type)}</Badge>
            <Badge variant="outline">{memory.scope === "kb" ? "知识库范围" : "全局范围"}</Badge>
            {memory.has_embedding ? (
              <span className="inline-flex items-center gap-1 text-xs text-muted">
                <CheckCircle2 className="h-3.5 w-3.5 text-brand" />
                已向量化
              </span>
            ) : null}
          </div>
          <p className="break-words text-sm font-medium leading-relaxed">{memory.content}</p>
          <div className="mt-2 grid gap-1 text-xs text-muted md:grid-cols-2">
            <div>来源：{memorySourceLabel(memory.source)}</div>
            <div>重要度：{memory.importance.toFixed(2)} · 置信度：{Math.round(memory.confidence * 100)}%</div>
            <div>结构键：{memory.key || "-"}</div>
            <div>结构值：{memory.value || "-"}</div>
            <div>更新：{formatMemoryDate(memory.updated_at)}</div>
            <div>{memory.expires_at ? `到期：${formatMemoryDate(memory.expires_at)}` : "长期有效"}</div>
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button type="button" variant="ghost" size="icon-sm" onClick={onEdit} disabled={busy} aria-label="编辑记忆">
            <Edit3 className="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="icon-sm"
            onClick={onDelete}
            disabled={busy || memory.status === "deleted"}
            aria-label="删除记忆"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>
    </article>
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
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="button" onClick={save} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            保存
          </Button>
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
