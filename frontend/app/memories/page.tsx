"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  BrainCircuit,
  ChevronDown,
  Download,
  Edit3,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import AppModal from "@/components/AppModal";
import Select from "@/components/Select";
import ThemeToggle from "@/components/ThemeToggle";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { LoadingState, StateView } from "@/components/ui/state-view";
import { getToken } from "@/lib/auth";
import {
  deleteMemory,
  exportMemories,
  listMemories,
  patchMemory,
  type UserMemory,
} from "@/lib/conversations-api";
import { cn } from "@/lib/utils";

type StatusFilter = "active" | "superseded" | "deleted" | "expired" | "all";
type TypeFilter = "all" | "fact" | "explicit" | "preference" | "constraint";
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
  { value: "fact", label: "事实" },
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
  const [exporting, setExporting] = useState(false);

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
    const embedded = rows.filter((m) => m.has_embedding).length;
    return { active, total: rows.length, embedded };
  }, [rows]);

  const handleStatusChange = (next: StatusFilter) => {
    setStatus(next);
    void refresh(next);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportMemories({ status });
      toast.success("记忆已导出");
    } catch (e) {
      toast.error((e as Error).message || "导出记忆失败");
    } finally {
      setExporting(false);
    }
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
    <div className="app-page min-h-dvh text-ink">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-4 sm:px-6">
          <Link href="/" className="app-nav-link app-nav-link-compact">
            <ArrowLeft className="h-4 w-4" />
            返回对话
          </Link>
          <div className="ml-auto">
            <ThemeToggle compact />
          </div>
        </div>
      </header>

      <main className="app-page-content mx-auto max-w-5xl px-4 py-7 sm:px-6 sm:py-10">
        <div className="admin-panel overflow-hidden">
          <div className="border-b border-surface-border/70 bg-surface-2/45 px-5 py-5 sm:px-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="min-w-0">
                <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
                  <span className="admin-icon-tile admin-icon-tile-brand rounded-md">
                    <BrainCircuit className="h-5 w-5" />
                  </span>
                  我的记忆
                </h1>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
                  管理对话中保存的长期记忆。只有有效记忆会注入后续上下文。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <p className="shrink-0 text-sm tabular-nums text-muted">
                  有效 <span className="font-semibold text-ink">{stats.active}</span>
                  <span className="mx-2 text-surface-border">·</span>
                  本页 <span className="font-semibold text-ink">{stats.total}</span>
                  <span className="mx-2 text-surface-border">·</span>
                  已向量化 <span className="font-semibold text-ink">{stats.embedded}</span>
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="h-[var(--control-h)] min-h-[var(--control-h)]"
                  onClick={() => void handleExport()}
                  disabled={exporting || rows.length === 0}
                >
                  {exporting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  导出
                </Button>
              </div>
            </div>
          </div>

          <section className="border-b border-surface-border/70 bg-surface px-5 py-3.5 sm:px-6">
            <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center">
              <label className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索内容、键、值或来源"
                  className="h-[var(--control-h)] pl-9"
                  aria-label="搜索记忆"
                />
              </label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:flex lg:shrink-0">
                <Select
                  value={status}
                  onChange={(e) => handleStatusChange(e.target.value as StatusFilter)}
                  options={STATUS_OPTIONS}
                  aria-label="按状态筛选"
                  className="h-[var(--control-h)] min-h-[var(--control-h)] w-full min-w-0 lg:w-[8.5rem]"
                />
                <Select
                  value={type}
                  onChange={(e) => setType(e.target.value as TypeFilter)}
                  options={TYPE_OPTIONS}
                  aria-label="按类型筛选"
                  className="h-[var(--control-h)] min-h-[var(--control-h)] w-full min-w-0 lg:w-[7.5rem]"
                />
                <Select
                  value={scope}
                  onChange={(e) => setScope(e.target.value as ScopeFilter)}
                  options={SCOPE_OPTIONS}
                  aria-label="按范围筛选"
                  className="h-[var(--control-h)] min-h-[var(--control-h)] w-full min-w-0 lg:w-[7.5rem]"
                />
                <Button
                  type="button"
                  variant="outline"
                  className="h-[var(--control-h)] min-h-[var(--control-h)]"
                  onClick={() => void refresh(status)}
                  disabled={refreshing}
                >
                  {refreshing ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  刷新
                </Button>
              </div>
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
              <div className="space-y-2">
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

      <ConfirmDialog
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
  const [detailsOpen, setDetailsOpen] = useState(false);
  const structureSummary = [memory.key, memory.value].filter(Boolean).join(" · ");
  const expiryLabel = memory.expires_at
    ? `到期 ${formatMemoryDate(memory.expires_at)}`
    : "长期有效";

  return (
    <article
      className={cn(
        "group relative overflow-hidden rounded-lg border border-surface-border/80 bg-surface transition-[border-color,background-color] duration-200",
        "hover:border-brand/30 hover:bg-surface/95"
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-0.5", memoryTypeAccent(memory.type))}
      />
      <div className="flex gap-3 py-3.5 pl-4 pr-3 sm:pl-5">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <MemoryChip tone={statusTone(memory.status)}>{statusLabel(memory.status)}</MemoryChip>
            <MemoryChip tone={typeTone(memory.type)}>{memoryTypeLabel(memory.type)}</MemoryChip>
            <MemoryChip tone="neutral">{memory.scope === "kb" ? "知识库" : "全局"}</MemoryChip>
          </div>

          <p className="line-clamp-2 break-words text-[15px] font-medium leading-6 text-ink">
            {memory.content}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span>{formatMemoryDate(memory.updated_at)}</span>
            <span aria-hidden className="text-surface-border">
              ·
            </span>
            <span>{expiryLabel}</span>
            {structureSummary ? (
              <>
                <span aria-hidden className="text-surface-border">
                  ·
                </span>
                <span className="max-w-[28rem] truncate font-mono text-[11px] text-muted/90">
                  {structureSummary}
                </span>
              </>
            ) : null}
          </div>

          {detailsOpen ? (
            <div className="mt-3 grid gap-2 rounded-md border border-surface-border/60 bg-surface-2/50 px-3 py-2.5 text-xs text-muted sm:grid-cols-2">
              <DetailItem label="结构键" value={memory.key || "—"} mono />
              <DetailItem label="结构值" value={memory.value || "—"} mono />
              <DetailItem label="来源" value={memorySourceLabel(memory.source)} />
              <DetailItem label="重要度" value={memory.importance.toFixed(2)} />
              <DetailItem label="置信度" value={`${Math.round(memory.confidence * 100)}%`} />
              <DetailItem label="过期" value={expiryLabel} />
              <DetailItem label="向量" value={memory.has_embedding ? "已向量化" : "未向量化"} />
            </div>
          ) : null}

          <button
            type="button"
            className="mt-2 inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-muted transition hover:bg-surface-2 hover:text-ink"
            onClick={() => setDetailsOpen((open) => !open)}
            aria-expanded={detailsOpen}
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition", detailsOpen && "rotate-180")} />
            {detailsOpen ? "收起详情" : "详情"}
          </button>
        </div>

        <div className="flex shrink-0 items-start gap-1 pt-0.5 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          <button
            type="button"
            className="admin-icon-action admin-icon-action-brand size-8"
            onClick={onEdit}
            disabled={busy}
            aria-label="编辑记忆"
            title="编辑记忆"
          >
            <Edit3 className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="admin-icon-action admin-icon-action-danger size-8"
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

function DetailItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-muted">{label}</div>
      <div className={cn("truncate font-medium text-ink", mono && "font-mono text-[11px]")}>
        {value}
      </div>
    </div>
  );
}

function MemoryChip({
  tone,
  children,
}: {
  tone: "success" | "danger" | "warning" | "muted" | "info" | "accent" | "neutral";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-md border px-2 text-[11px] font-medium leading-none tracking-wide",
        tone === "success" &&
          "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
        tone === "danger" &&
          "border-red-500/30 bg-red-500/15 text-red-700 dark:text-red-300",
        tone === "warning" &&
          "border-amber-500/30 bg-amber-500/15 text-amber-800 dark:text-amber-300",
        tone === "muted" &&
          "border-surface-border/80 bg-surface-2/80 text-muted",
        tone === "info" &&
          "border-sky-500/30 bg-sky-500/15 text-sky-800 dark:text-sky-300",
        tone === "accent" &&
          "border-brand/30 bg-brand/15 text-brand dark:text-sky-300",
        tone === "neutral" &&
          "border-surface-border/80 bg-surface-2/70 text-ink/85"
      )}
    >
      {children}
    </span>
  );
}

function statusTone(
  status: UserMemory["status"]
): "success" | "danger" | "warning" | "muted" {
  if (status === "active") return "success";
  if (status === "deleted") return "danger";
  if (status === "expired") return "warning";
  return "muted";
}

function typeTone(
  type: UserMemory["type"]
): "info" | "accent" | "warning" | "neutral" {
  if (type === "preference") return "info";
  if (type === "constraint") return "warning";
  if (type === "explicit") return "accent";
  return "neutral";
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
  const [neverExpires, setNeverExpires] = useState(true);
  const [expiresLocal, setExpiresLocal] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (!memory) return;
    setContent(memory.content);
    setValue(memory.value ?? "");
    setImportance(memory.importance);
    setNeverExpires(!memory.expires_at);
    setExpiresLocal(toDatetimeLocalValue(memory.expires_at));
    setAdvancedOpen(Boolean(memory.expires_at));
  }, [memory]);

  const save = async () => {
    if (!memory) return;
    const nextContent = content.trim();
    if (nextContent.length < 4) {
      toast.error("记忆内容至少需要 4 个字符");
      return;
    }
    let expires_at: string | null = null;
    if (!neverExpires) {
      if (!expiresLocal) {
        toast.error("请选择到期时间，或勾选长期有效");
        return;
      }
      const parsed = fromDatetimeLocalValue(expiresLocal);
      if (!parsed) {
        toast.error("到期时间格式无效");
        return;
      }
      expires_at = parsed;
    }
    onSaving(memory.id);
    try {
      const updated = await patchMemory(memory.id, {
        content: nextContent,
        value: value.trim() || undefined,
        importance,
        status: memory.status === "deleted" ? "deleted" : "active",
        expires_at,
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
    <AppModal
      open={memory !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="编辑记忆"
      size="md"
      busy={busy}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="button" onClick={save} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            保存
          </Button>
        </>
      }
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

        <div className="space-y-2 rounded-lg border border-surface-border/70 bg-surface-2/40 p-3">
          <div className="text-xs font-medium text-muted">过期时间</div>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={neverExpires}
              onChange={(e) => {
                const next = e.target.checked;
                setNeverExpires(next);
                if (next) {
                  setExpiresLocal("");
                } else if (!expiresLocal) {
                  setExpiresLocal(toDatetimeLocalValue(defaultExpiryIso()));
                }
              }}
              disabled={busy}
              className="accent-brand"
            />
            长期有效（不过期）
          </label>
          {!neverExpires ? (
            <label className="block">
              <div className="mb-1 text-xs text-muted">到期于</div>
              <Input
                type="datetime-local"
                value={expiresLocal}
                onChange={(e) => setExpiresLocal(e.target.value)}
                disabled={busy}
              />
            </label>
          ) : null}
        </div>

        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 text-xs font-medium text-muted transition hover:text-ink"
          onClick={() => setAdvancedOpen((open) => !open)}
          aria-expanded={advancedOpen}
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition", advancedOpen && "rotate-180")} />
          高级选项
        </button>

        {advancedOpen ? (
          <div className="space-y-3 rounded-lg border border-surface-border/70 bg-surface-2/40 p-3">
            <label className="block">
              <div className="mb-1 text-xs font-medium text-muted">结构值</div>
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                maxLength={500}
                disabled={busy}
              />
            </label>
            <label className="block">
              <div className="mb-1 text-xs font-medium text-muted">
                重要度 {importance.toFixed(2)}
              </div>
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
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}

function memoryTypeAccent(type: UserMemory["type"]) {
  if (type === "preference") return "bg-sky-500/80";
  if (type === "constraint") return "bg-amber-500/80";
  if (type === "explicit") return "bg-emerald-500/80";
  return "bg-brand/70";
}

function memoryTypeLabel(type: UserMemory["type"]) {
  if (type === "preference") return "偏好";
  if (type === "constraint") return "约束";
  if (type === "explicit") return "显式";
  if (type === "fact") return "事实";
  return type;
}

function memorySourceLabel(source: UserMemory["source"]) {
  if (source === "auto_rule") return "自动提取";
  if (source === "auto_session") return "会话自动";
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
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toDatetimeLocalValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromDatetimeLocalValue(local: string): string | null {
  if (!local) return null;
  const date = new Date(local);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

function defaultExpiryIso(): string {
  const date = new Date();
  date.setDate(date.getDate() + 180);
  return date.toISOString();
}
