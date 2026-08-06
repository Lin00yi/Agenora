"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  GitBranch,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  getTrace,
  listTraces,
  type AdminObservationNode,
  type AdminTraceDetail,
  type AdminTraceSummary,
} from "@/lib/admin-api";
import { cn } from "@/lib/cn";
import { Button, buttonVariants } from "@/components/ui/button";
import AdminShell from "../AdminShell";
import { PageSkeleton, StateView } from "@/components/ui/state-view";

const PAGE_SIZE = 50;

const paginationButtonClass = cn(
  buttonVariants({ variant: "outline" }),
  "shrink-0"
);

/**
 * /admin/traces — internal end-to-end span trees (DB Trace).
 */
export default function AdminTracesPage() {
  return (
    <AdminShell title="后台管理 · 追踪">
      <TracesPanel />
    </AdminShell>
  );
}

function TracesPanel() {
  const [traces, setTraces] = useState<AdminTraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [conversationId, setConversationId] = useState("");
  const [userId, setUserId] = useState("");
  const [appliedConversationId, setAppliedConversationId] = useState("");
  const [appliedUserId, setAppliedUserId] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminTraceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(
    (nextOffset = 0, conv = appliedConversationId, uid = appliedUserId) => {
      setLoading(true);
      listTraces({
        limit: PAGE_SIZE,
        offset: nextOffset,
        conversation_id: conv || undefined,
        user_id: uid || undefined,
      })
        .then((r) => {
          setTraces(r.traces);
          setTotal(r.total);
          setOffset(r.offset);
        })
        .catch((e) => toast.error((e as Error).message))
        .finally(() => setLoading(false));
    },
    [appliedConversationId, appliedUserId]
  );

  useEffect(() => {
    load(0);
  }, [load]);

  const openDetail = (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setDetail(null);
    getTrace(id)
      .then(setDetail)
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setDetailLoading(false));
  };

  const applyFilters = () => {
    setAppliedConversationId(conversationId.trim());
    setAppliedUserId(userId.trim());
    setSelectedId(null);
    setDetail(null);
  };

  const clearFilters = () => {
    setConversationId("");
    setUserId("");
    setAppliedConversationId("");
    setAppliedUserId("");
    setSelectedId(null);
    setDetail(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-brand">
            全链路追踪
          </p>
          <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <GitBranch className="h-5 w-5 text-brand" />
            Trace 记录
          </h2>
          <p className="mt-2 text-sm text-muted">
            共 {total} 条请求级 Trace，可按会话 / 用户筛选并展开 span 树。
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => load(offset)}>
          <RefreshCw className="h-4 w-4" />
          刷新
        </Button>
      </div>

      <div className="admin-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 space-y-1.5 text-xs">
          <span className="font-medium text-muted">conversation_id</span>
          <input
            className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/20"
            value={conversationId}
            onChange={(e) => setConversationId(e.target.value)}
            placeholder="可选"
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
          />
        </label>
        <label className="min-w-0 flex-1 space-y-1.5 text-xs">
          <span className="font-medium text-muted">user_id</span>
          <input
            className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/20"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="可选"
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
          />
        </label>
        <div className="flex shrink-0 gap-2">
          <Button type="button" onClick={applyFilters}>
            <Search className="h-4 w-4" />
            筛选
          </Button>
          {(appliedConversationId || appliedUserId) && (
            <Button type="button" variant="outline" onClick={clearFilters}>
              <X className="h-4 w-4" />
              清除
            </Button>
          )}
        </div>
      </div>

      {loading ? (
        <PageSkeleton />
      ) : traces.length === 0 ? (
        <StateView
          title="还没有 Trace 记录"
          description="开启 TRACE_ENABLED 后，完成一轮对话即可在此查看端到端 span 树与延迟。"
        />
      ) : (
        <>
          <div className="admin-panel overflow-x-auto">
            <table className="admin-table">
              <thead>
                <tr>
                  <th className="w-[18%]">时间</th>
                  <th className="w-[10%]">状态</th>
                  <th className="w-[12%] text-right">耗时</th>
                  <th className="w-[12%] text-right">成本</th>
                  <th className="w-[10%] text-right">Spans</th>
                  <th className="w-[19%]">会话</th>
                  <th className="w-[19%]">用户</th>
                </tr>
              </thead>
              <tbody>
                {traces.map((t) => {
                  const active = selectedId === t.id;
                  return (
                    <tr
                      key={t.id}
                      className={cn(
                        "cursor-pointer transition",
                        active && "bg-brand/5"
                      )}
                      onClick={() => openDetail(t.id)}
                    >
                      <td className="text-xs text-muted">
                        {formatDateTime(t.started_at)}
                      </td>
                      <td>
                        <StatusChip status={t.status} />
                      </td>
                      <td className="text-right tabular-nums text-sm">
                        {formatDuration(t.duration_ms)}
                      </td>
                      <td className="text-right tabular-nums text-sm text-muted">
                        {formatCost(t.total_cost_usd)}
                      </td>
                      <td className="text-right tabular-nums text-sm">
                        {t.observation_count}
                      </td>
                      <td className="max-w-0 truncate font-mono text-xs text-muted" title={t.conversation_id ?? undefined}>
                        {t.conversation_id || "—"}
                      </td>
                      <td className="max-w-0 truncate font-mono text-xs text-muted" title={t.user_id ?? undefined}>
                        {t.user_id || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted">
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={paginationButtonClass}
                  disabled={offset <= 0}
                  onClick={() => load(Math.max(0, offset - PAGE_SIZE))}
                >
                  上一页
                </button>
                <button
                  type="button"
                  className={paginationButtonClass}
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => load(offset + PAGE_SIZE)}
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {selectedId && (
        <TraceDetailCard
          loading={detailLoading}
          detail={detail}
          onClose={() => {
            setSelectedId(null);
            setDetail(null);
          }}
        />
      )}
    </div>
  );
}

function TraceDetailCard({
  loading,
  detail,
  onClose,
}: {
  loading: boolean;
  detail: AdminTraceDetail | null;
  onClose: () => void;
}) {
  return (
    <section className="admin-panel overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-surface-border/70 bg-surface-2/35 px-5 py-4">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Span 树</h3>
          {detail ? (
            <p className="mt-1 truncate font-mono text-xs text-muted" title={detail.id}>
              {detail.id}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted">加载中…</p>
          )}
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
          关闭
        </Button>
      </div>

      {loading && (
        <div className="p-5">
          <PageSkeleton />
        </div>
      )}

      {!loading && detail && (
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap gap-2 text-xs">
            <StatusChip status={detail.status} />
            <span className="chip chip-muted">
              总耗时 {formatDuration(detail.duration_ms)}
            </span>
            <span className="chip chip-muted">
              成本 {formatCost(detail.total_cost_usd)}
            </span>
            {detail.metadata?.kb_id != null && (
              <span className="chip chip-muted">
                kb {String(detail.metadata.kb_id)}
              </span>
            )}
            {detail.metadata?.model != null && (
              <span className="chip chip-muted">
                model {String(detail.metadata.model)}
              </span>
            )}
          </div>

          {(detail.input_preview || detail.output_preview) && (
            <div className="grid gap-3 md:grid-cols-2">
              {detail.input_preview && (
                <PreviewBlock title="Input" text={detail.input_preview} />
              )}
              {detail.output_preview && (
                <PreviewBlock title="Output" text={detail.output_preview} />
              )}
            </div>
          )}

          {detail.observations.length === 0 ? (
            <p className="text-sm text-muted">该 Trace 没有子 observation。</p>
          ) : (
            <div className="space-y-1 border-t border-surface-border/60 pt-4">
              {detail.observations.map((node) => (
                <ObservationRow key={node.id} node={node} depth={0} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ObservationRow({
  node,
  depth,
}: {
  node: AdminObservationNode;
  depth: number;
}) {
  const children = node.children ?? [];
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = children.length > 0;

  return (
    <div>
      <div
        className={cn(
          "group flex items-start gap-2 rounded-lg px-2 py-2 transition hover:bg-surface-2/50",
          node.status === "error" && "bg-danger/5"
        )}
        style={{ paddingLeft: `${depth * 1.25 + 0.5}rem` }}
      >
        <button
          type="button"
          className={cn(
            "mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted",
            !hasChildren && "invisible"
          )}
          aria-label={open ? "折叠" : "展开"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <TypeChip type={node.type} />
            <span className="truncate text-sm font-medium">{node.name}</span>
            <StatusChip status={node.status} />
            <span className="tabular-nums text-xs text-muted">
              {formatDuration(node.duration_ms)}
            </span>
            {node.model && (
              <span className="truncate text-xs text-muted">{node.model}</span>
            )}
            {node.cost_usd != null && (
              <span className="tabular-nums text-xs text-muted">
                {formatCost(node.cost_usd)}
              </span>
            )}
          </div>
          {node.error && (
            <p className="mt-1 text-xs text-danger">{node.error}</p>
          )}
          {(node.input_preview || node.output_preview) && (
            <details className="mt-1.5 text-xs text-muted">
              <summary className="cursor-pointer select-none hover:text-ink">
                预览 IO
              </summary>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                {node.input_preview && (
                  <PreviewBlock title="in" text={node.input_preview} compact />
                )}
                {node.output_preview && (
                  <PreviewBlock title="out" text={node.output_preview} compact />
                )}
              </div>
            </details>
          )}
        </div>
      </div>

      {hasChildren && open && (
        <div>
          {children.map((child) => (
            <ObservationRow key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function PreviewBlock({
  title,
  text,
  compact,
}: {
  title: string;
  text: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-surface-border/80 bg-surface",
        compact ? "p-2" : "p-3"
      )}
    >
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
        {title}
      </div>
      <pre
        className={cn(
          "whitespace-pre-wrap break-words font-mono text-ink",
          compact ? "max-h-40 overflow-auto text-[11px] leading-relaxed" : "max-h-56 overflow-auto text-xs leading-relaxed"
        )}
      >
        {text}
      </pre>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  if (status === "error") {
    return <span className="chip chip-danger">error</span>;
  }
  return <span className="chip chip-success">{status || "ok"}</span>;
}

function TypeChip({ type }: { type: string }) {
  const tone =
    type === "generation"
      ? "chip-brand"
      : type === "tool"
        ? "chip-muted"
        : "chip-muted";
  return <span className={cn("chip shrink-0", tone)}>{type}</span>;
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
}

function formatCost(usd: number | null | undefined): string {
  if (usd == null) return "—";
  if (usd === 0) return "$0";
  if (usd < 0.0001) return `$${usd.toExponential(1)}`;
  return `$${usd.toFixed(4)}`;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}
