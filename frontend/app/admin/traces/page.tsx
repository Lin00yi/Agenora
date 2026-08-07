"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Copy,
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
import { LoadingState, PageSkeleton, StateView } from "@/components/ui/state-view";

const PAGE_SIZE = 30;

const paginationButtonClass = cn(
  buttonVariants({ variant: "outline" }),
  "shrink-0"
);

/**
 * /admin/traces — master/detail layout with duration waterfall.
 */
export default function AdminTracesPage() {
  return <TracesPanel />;
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
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const d = await getTrace(id);
      setDetail(d);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const load = useCallback(
    async (nextOffset = 0) => {
      setLoading(true);
      try {
        const r = await listTraces({
          limit: PAGE_SIZE,
          offset: nextOffset,
          conversation_id: appliedConversationId || undefined,
          user_id: appliedUserId || undefined,
        });
        setTraces(r.traces);
        setTotal(r.total);
        setOffset(r.offset);

        if (r.traces.length === 0) {
          setSelectedId(null);
          setDetail(null);
          return;
        }
        const current = selectedIdRef.current;
        const keep =
          current && r.traces.some((t) => t.id === current)
            ? current
            : r.traces[0].id;
        await openDetail(keep);
      } catch (e) {
        toast.error((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [appliedConversationId, appliedUserId, openDetail]
  );

  useEffect(() => {
    void load(0);
    // Re-fetch only when filters change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedConversationId, appliedUserId]);

  const applyFilters = () => {
    setAppliedConversationId(conversationId.trim());
    setAppliedUserId(userId.trim());
  };

  const clearFilters = () => {
    setConversationId("");
    setUserId("");
    setAppliedConversationId("");
    setAppliedUserId("");
  };

  const maxDuration = useMemo(
    () => Math.max(1, ...traces.map((t) => t.duration_ms ?? 0)),
    [traces]
  );

  return (
    <div className="space-y-5">
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
            共 {total} 条请求。点选左侧记录，右侧查看 span 树与耗时瀑布。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={loading}
          onClick={() => void load(offset)}
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          刷新
        </Button>
      </div>

      <div className="admin-panel flex flex-col gap-3 p-4 lg:flex-row lg:items-end">
        <label className="min-w-0 flex-1 space-y-1.5 text-xs">
          <span className="font-medium text-muted">会话 ID</span>
          <input
            className="admin-input"
            value={conversationId}
            onChange={(e) => setConversationId(e.target.value)}
            placeholder="conversation_id"
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
          />
        </label>
        <label className="min-w-0 flex-1 space-y-1.5 text-xs">
          <span className="font-medium text-muted">用户 ID</span>
          <input
            className="admin-input"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="user_id"
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

      {loading && traces.length === 0 ? (
        <PageSkeleton />
      ) : traces.length === 0 ? (
        <StateView
          title="还没有 Trace 记录"
          description="开启 TRACE_ENABLED 后，完成一轮对话即可在此查看端到端 span 树与延迟。"
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div className="admin-panel flex max-h-[min(70dvh,52rem)] flex-col overflow-hidden">
            <div className="border-b border-surface-border/70 px-4 py-3 text-xs font-semibold text-muted">
              请求列表
            </div>
            <div className="flex-1 overflow-y-auto">
              {traces.map((t) => {
                const active = selectedId === t.id;
                const pct = Math.min(
                  100,
                  ((t.duration_ms ?? 0) / maxDuration) * 100
                );
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => void openDetail(t.id)}
                    className={cn(
                      "block w-full border-b border-l-[3px] border-surface-border/40 px-4 py-3 text-left transition",
                      active
                        ? "border-l-brand bg-brand/10"
                        : "border-l-transparent hover:bg-surface-2/60"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-muted">
                        {formatDateTime(t.started_at)}
                      </span>
                      <StatusChip status={t.status} />
                    </div>
                    <div className="mt-1.5 flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold tabular-nums">
                        {formatDuration(t.duration_ms)}
                      </span>
                      <span className="text-xs text-muted">
                        {t.observation_count} spans · {formatCost(t.total_cost_usd)}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          t.status === "error" ? "bg-danger/70" : "bg-brand/70"
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="mt-2 truncate font-mono text-[11px] text-muted">
                      {shortId(t.conversation_id) || "无会话"}
                      {t.user_id ? ` · ${shortId(t.user_id)}` : ""}
                    </div>
                  </button>
                );
              })}
            </div>
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between gap-2 border-t border-surface-border/70 px-3 py-2">
                <button
                  type="button"
                  className={paginationButtonClass}
                  disabled={offset <= 0 || loading}
                  onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
                >
                  上一页
                </button>
                <span className="text-[11px] text-muted">
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
                </span>
                <button
                  type="button"
                  className={paginationButtonClass}
                  disabled={offset + PAGE_SIZE >= total || loading}
                  onClick={() => void load(offset + PAGE_SIZE)}
                >
                  下一页
                </button>
              </div>
            )}
          </div>

          <div className="admin-panel min-h-[24rem] overflow-hidden">
            {detailLoading && !detail ? (
              <div className="flex min-h-[24rem] items-center justify-center p-6">
                <LoadingState
                  label="加载 Trace"
                  description="正在拉取 span 树与耗时。"
                  className="w-full max-w-sm"
                />
              </div>
            ) : detail ? (
              <TraceDetail detail={detail} loading={detailLoading} />
            ) : (
              <div className="flex min-h-[24rem] items-center justify-center p-6">
                <StateView
                  title="选择一条 Trace"
                  description="从左侧列表点选请求，查看完整 span 树。"
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TraceDetail({
  detail,
  loading,
}: {
  detail: AdminTraceDetail;
  loading: boolean;
}) {
  const totalMs = Math.max(1, detail.duration_ms ?? 1);
  const flat = detail.observations_flat?.length
    ? detail.observations_flat
    : flattenTree(detail.observations);
  const rootStart = detail.started_at
    ? Date.parse(detail.started_at)
    : flat[0]?.started_at
      ? Date.parse(flat[0].started_at)
      : 0;

  return (
    <div className={cn("flex h-full max-h-[min(70dvh,52rem)] flex-col", loading && "opacity-70")}>
      <div className="border-b border-surface-border/70 bg-surface-2/35 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold">Span 树</h3>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="truncate font-mono text-xs text-muted">{detail.id}</code>
              <CopyBtn value={detail.id} label="复制 Trace ID" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <StatusChip status={detail.status} />
            <span className="chip chip-muted">{formatDuration(detail.duration_ms)}</span>
            <span className="chip chip-muted">{formatCost(detail.total_cost_usd)}</span>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {detail.conversation_id && (
            <span className="inline-flex items-center gap-1.5">
              会话 <code className="font-mono">{shortId(detail.conversation_id)}</code>
              <CopyBtn value={detail.conversation_id} label="复制会话 ID" />
            </span>
          )}
          {detail.user_id && (
            <span className="inline-flex items-center gap-1.5">
              用户 <code className="font-mono">{shortId(detail.user_id)}</code>
              <CopyBtn value={detail.user_id} label="复制用户 ID" />
            </span>
          )}
          {detail.metadata?.model != null && (
            <span>模型 {String(detail.metadata.model)}</span>
          )}
          {detail.metadata?.kb_id != null && (
            <span>KB {shortId(String(detail.metadata.kb_id))}</span>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {(detail.input_preview || detail.output_preview) && (
          <div className="grid gap-3 md:grid-cols-2">
            {detail.input_preview && (
              <PreviewBlock title="输入" text={detail.input_preview} />
            )}
            {detail.output_preview && (
              <PreviewBlock title="输出" text={detail.output_preview} />
            )}
          </div>
        )}

        {detail.observations.length === 0 ? (
          <p className="text-sm text-muted">该 Trace 没有子 observation。</p>
        ) : (
          <div className="space-y-1">
            <div className="mb-2 flex items-center justify-between text-xs text-muted">
              <span>时间线（相对整次请求）</span>
              <span>总长 {formatDuration(detail.duration_ms)}</span>
            </div>
            {detail.observations.map((node) => (
              <ObservationRow
                key={node.id}
                node={node}
                depth={0}
                totalMs={totalMs}
                rootStart={rootStart}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ObservationRow({
  node,
  depth,
  totalMs,
  rootStart,
}: {
  node: AdminObservationNode;
  depth: number;
  totalMs: number;
  rootStart: number;
}) {
  const children = node.children ?? [];
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = children.length > 0;
  const startMs = node.started_at ? Date.parse(node.started_at) - rootStart : 0;
  const dur = Math.max(0, node.duration_ms ?? 0);
  const leftPct = Math.max(0, Math.min(100, (startMs / totalMs) * 100));
  const widthPct = Math.max(0.8, Math.min(100 - leftPct, (dur / totalMs) * 100));
  const slow = dur >= 1000 || dur / totalMs >= 0.35;

  return (
    <div>
      <div
        className={cn(
          "rounded-lg px-2 py-2 transition hover:bg-surface-2/50",
          node.status === "error" && "bg-danger/5"
        )}
        style={{ marginLeft: `${depth * 0.85}rem` }}
      >
        <div className="flex items-start gap-2">
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
              {node.status === "error" && <StatusChip status="error" />}
              <span
                className={cn(
                  "tabular-nums text-xs",
                  slow ? "font-semibold text-warning" : "text-muted"
                )}
              >
                {formatDuration(node.duration_ms)}
              </span>
              {node.model && (
                <span className="truncate text-xs text-muted">{node.model}</span>
              )}
              {node.cost_usd != null && node.cost_usd > 0 && (
                <span className="tabular-nums text-xs text-muted">
                  {formatCost(node.cost_usd)}
                </span>
              )}
            </div>

            <div className="relative mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                className={cn(
                  "absolute top-0 h-full rounded-full",
                  node.type === "generation"
                    ? "bg-brand/75"
                    : node.type === "tool"
                      ? "bg-info/70"
                      : "bg-muted/45",
                  node.status === "error" && "!bg-danger/70"
                )}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                title={`offset ${formatDuration(startMs)} · ${formatDuration(dur)}`}
              />
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
                    <PreviewBlock title="输入" text={node.input_preview} compact />
                  )}
                  {node.output_preview && (
                    <PreviewBlock title="输出" text={node.output_preview} compact />
                  )}
                </div>
              </details>
            )}
          </div>
        </div>
      </div>

      {hasChildren && open && (
        <div>
          {children.map((child) => (
            <ObservationRow
              key={child.id}
              node={child}
              depth={depth + 1}
              totalMs={totalMs}
              rootStart={rootStart}
            />
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
          compact
            ? "max-h-40 overflow-auto text-[11px] leading-relaxed"
            : "max-h-56 overflow-auto text-xs leading-relaxed"
        )}
      >
        {text}
      </pre>
    </div>
  );
}

function CopyBtn({ value, label }: { value: string; label: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className="admin-icon-action inline-flex size-6 rounded text-muted hover:text-ink"
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(value);
          toast.success("已复制");
        } catch {
          toast.error("复制失败");
        }
      }}
    >
      <Copy className="h-3 w-3" />
    </button>
  );
}

function StatusChip({ status }: { status: string }) {
  if (status === "error") {
    return <span className="chip chip-danger">失败</span>;
  }
  return <span className="chip chip-success">成功</span>;
}

function TypeChip({ type }: { type: string }) {
  const label =
    type === "generation" ? "LLM" : type === "tool" ? "工具" : "步骤";
  const tone = type === "generation" ? "chip-brand" : "chip-muted";
  return <span className={cn("chip shrink-0", tone)}>{label}</span>;
}

function flattenTree(nodes: AdminObservationNode[]): AdminObservationNode[] {
  const out: AdminObservationNode[] = [];
  const walk = (list: AdminObservationNode[]) => {
    for (const n of list) {
      out.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

function shortId(id: string | null | undefined): string {
  if (!id) return "";
  if (id.length <= 12) return id;
  return `${id.slice(0, 8)}…`;
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
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
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}
