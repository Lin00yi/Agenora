"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Copy,
  GitBranch,
  MessageSquareText,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { toast } from "@/lib/toast";

import {
  getTrace,
  listTraces,
  type AdminObservationNode,
  type AdminTraceDetail,
  type AdminTraceSummary,
} from "@/lib/admin-api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { PageSkeleton, StateView } from "@/components/ui/state-view";
import Select from "@/components/Select";
import { SpanWaterfall } from "@/components/admin/SpanWaterfall";
import { usePreviewPanel } from "@/components/preview/PreviewPanelProvider";

const PAGE_SIZE = 30;

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
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [conversationId, setConversationId] = useState("");
  const [userId, setUserId] = useState("");
  const [minRisk, setMinRisk] = useState<"low" | "medium" | "high">("low");
  const [appliedConversationId, setAppliedConversationId] = useState("");
  const [appliedUserId, setAppliedUserId] = useState("");
  const [appliedMinRisk, setAppliedMinRisk] = useState<"low" | "medium" | "high">("low");

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
    async (nextOffset = 0, refreshDetail = true) => {
      setRefreshing(true);
      try {
        const r = await listTraces({
          limit: PAGE_SIZE,
          offset: nextOffset,
          conversation_id: appliedConversationId || undefined,
          user_id: appliedUserId || undefined,
          min_risk: appliedMinRisk,
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
        if (refreshDetail || keep !== current) {
          await openDetail(keep);
        }
      } catch (e) {
        toast.error((e as Error).message);
      } finally {
        setInitialLoading(false);
        setRefreshing(false);
      }
    },
    [appliedConversationId, appliedUserId, appliedMinRisk, openDetail]
  );

  useEffect(() => {
    void load(0);
    // Re-fetch only when filters change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedConversationId, appliedUserId, appliedMinRisk]);

  const applyFilters = () => {
    setAppliedConversationId(conversationId.trim());
    setAppliedUserId(userId.trim());
    setAppliedMinRisk(minRisk);
  };

  const clearFilters = () => {
    setConversationId("");
    setUserId("");
    setMinRisk("low");
    setAppliedConversationId("");
    setAppliedUserId("");
    setAppliedMinRisk("low");
  };

  const maxDuration = useMemo(
    () => Math.max(1, ...traces.map((t) => t.duration_ms ?? 0)),
    [traces]
  );

  const filtersActive =
    !!appliedConversationId || !!appliedUserId || appliedMinRisk !== "low";

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
            共 {total} 条请求。点选左侧记录，右侧查看 span 树、注入风险与已过滤 chunk。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={refreshing}
          onClick={() => void load(offset, false)}
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
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
        <div className="min-w-0 flex-1 space-y-1.5 text-xs sm:max-w-[12rem]">
          <span className="block font-medium text-muted">注入风险</span>
          <Select
            aria-label="注入风险"
            value={minRisk}
            onChange={(e) =>
              setMinRisk(e.target.value as "low" | "medium" | "high")
            }
            options={[
              { value: "low", label: "全部" },
              { value: "medium", label: "中 / 高" },
              { value: "high", label: "仅高" },
            ]}
          />
        </div>
        <div className="flex shrink-0 gap-2">
          <Button type="button" onClick={applyFilters}>
            <Search className="h-4 w-4" />
            筛选
          </Button>
          {filtersActive && (
            <Button type="button" variant="outline" onClick={clearFilters}>
              <X className="h-4 w-4" />
              清除
            </Button>
          )}
        </div>
      </div>

      {initialLoading ? (
        <PageSkeleton />
      ) : traces.length === 0 ? (
        <StateView
          title="还没有 Trace 记录"
          description="开启 TRACE_ENABLED 后，完成一轮对话即可在此查看端到端 span 树与延迟。每个 span 可点「预览 IO」查看输入/输出。"
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div className="admin-panel relative flex max-h-[min(70dvh,52rem)] flex-col overflow-hidden" aria-busy={refreshing}>
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
                      <div className="flex items-center gap-1.5">
                        <RiskChip risk={metaRisk(t.metadata)} />
                        <StatusChip status={t.status} />
                      </div>
                    </div>
                    <div className="mt-1.5 flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold tabular-nums">
                        {formatDuration(t.duration_ms)}
                      </span>
                      <span className="text-xs text-muted">
                        {t.observation_count} spans · {formatCost(t.total_cost_usd)}
                        {metaSuspiciousCount(t.metadata) > 0
                          ? ` · 滤 ${metaSuspiciousCount(t.metadata)}`
                          : ""}
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
            {total > 0 ? (
              <div className="border-t border-surface-border/70 px-3 py-2">
                <Pagination
                  total={total}
                  offset={offset}
                  pageSize={PAGE_SIZE}
                  onOffsetChange={(next) => void load(next)}
                  disabled={refreshing}
                />
              </div>
            ) : null}
            {refreshing ? (
              <StateView variant="loading" overlay density="compact" title="正在刷新 Trace" />
            ) : null}
          </div>

          <div className="admin-panel relative min-h-[24rem] overflow-hidden">
            {detailLoading && !detail ? (
              <div className="flex min-h-[24rem] items-center justify-center p-6">
                <StateView
                  variant="loading"
                  title="加载 Trace"
                  description="正在拉取 span 树与耗时。"
                  className="w-full max-w-sm"
                />
              </div>
            ) : detail ? (
              <>
                <TraceDetail detail={detail} loading={detailLoading} />
                {detailLoading ? (
                  <StateView variant="loading" overlay density="compact" title="正在刷新 Trace 详情" />
                ) : null}
              </>
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
  const risk = metaRisk(detail.metadata);
  const reasons = metaReasons(detail.metadata);
  const filteredChunks = metaFilteredChunks(detail.metadata);
  const suspiciousCount = metaSuspiciousCount(detail.metadata);
  const promptVersions = metaPromptVersions(detail.metadata);
  const runtime = typeof detail.metadata?.agent_runtime === "string"
    ? detail.metadata.agent_runtime
    : "历史记录";
  const schemaVersion = typeof detail.metadata?.trace_schema_version === "number"
    ? detail.metadata.trace_schema_version
    : null;
  const ttftMs = typeof detail.metadata?.ttft_ms === "number" && Number.isFinite(detail.metadata.ttft_ms)
    ? Math.max(0, detail.metadata.ttft_ms)
    : null;

  return (
    <div className={cn("flex h-full max-h-[min(70dvh,52rem)] flex-col", loading && "opacity-70")}>
      <div className="border-b border-surface-border/70 bg-surface-2/35 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold">执行链路</h3>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="truncate font-mono text-xs text-muted">{detail.id}</code>
              <CopyBtn value={detail.id} label="复制 Trace ID" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <RiskChip risk={risk} />
            <StatusChip status={detail.status} />
            <span className="chip chip-muted">{formatDuration(detail.duration_ms)}</span>
            {ttftMs != null && <span className="chip chip-muted tabular-nums" title="从请求 Trace 开始到首个流式文本 token 发出的耗时">TTFT {formatDuration(ttftMs)}</span>}
            <span className="chip chip-muted">{formatCost(detail.total_cost_usd)}</span>
            {suspiciousCount > 0 && (
              <span className="chip chip-warning">过滤 {suspiciousCount} chunk</span>
            )}
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
          <span>运行时 {runtime}</span>
          {schemaVersion != null && <span>Trace v{schemaVersion}</span>}
        </div>
        {reasons.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {reasons.map((reason) => (
              <span key={reason} className="chip chip-muted font-mono text-[10px]">
                {reason}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        <TraceIoPreviewButton
          title={`Trace ${shortId(detail.id)}`}
          subtitle="会话级输入 / 输出"
          input={detail.input_preview}
          output={detail.output_preview}
          metadata={detail.metadata}
        />

        {promptVersions.length > 0 ? <PromptVersionsPanel entries={promptVersions} /> : null}

        {filteredChunks.length > 0 && (
          <FilteredChunksPanel chunks={filteredChunks} />
        )}

        {detail.observations.length === 0 ? (
          <p className="text-sm text-muted">
            该 Trace 没有可展示的执行节点（通常为历史版本或中断前未采集的记录），不作为当前 ReAct 链路样本。
          </p>
        ) : (
          <SpanWaterfall
            nodes={detail.observations}
            totalMs={totalMs}
            rootStart={rootStart}
          />
        )}
      </div>
    </div>
  );
}

type PromptVersionEntry = {
  surface: string;
  key: string;
  version: number | null;
  digest: string | null;
  source: "registry" | "code";
};

function PromptVersionsPanel({ entries }: { entries: PromptVersionEntry[] }) {
  return (
    <section className="rounded-lg border border-brand/20 bg-brand/5 p-3" aria-label="本轮 Prompt 版本">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="flex text-balance items-center gap-2 text-sm font-semibold text-ink"><MessageSquareText className="h-4 w-4 text-brand" />本轮 Prompt 版本</h4>
          <p className="mt-1 text-pretty text-xs leading-5 text-muted">仅展示实际生效的模板键、版本与摘要；Prompt 正文不会进入 Trace。</p>
        </div>
        <span className="chip chip-muted tabular-nums">{entries.length} 个</span>
      </div>
      <ul className="mt-3 divide-y divide-brand/15 overflow-hidden rounded-md border border-brand/15 bg-surface">
        {entries.map((entry) => (
          <li key={`${entry.surface}-${entry.key}-${entry.version ?? "code"}-${entry.digest ?? ""}`} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-3 py-2 text-xs">
            <div className="min-w-0">
              <span className="font-medium text-ink">{entry.surface}</span>
              <code className="ml-2 break-all font-mono text-[11px] text-muted">{entry.key}</code>
            </div>
            <div className="flex items-center gap-2 text-muted">
              <span className={cn("chip", entry.source === "registry" ? "chip-success" : "chip-muted")}>
                {entry.source === "registry" ? `已发布 v${entry.version ?? "?"}` : "代码默认"}
              </span>
              {entry.digest ? <code className="font-mono text-[10px]">{entry.digest.slice(0, 12)}</code> : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

type FilteredChunkRow = {
  channel?: string;
  query?: string | null;
  kb_id?: string | null;
  doc_id?: string | null;
  filename?: string | null;
  score?: number | null;
  level?: string;
  reasons?: string[];
  preview?: string;
  block_index?: number;
};

function FilteredChunksPanel({ chunks }: { chunks: FilteredChunkRow[] }) {
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/5 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-ink">安全审计 · 已过滤 chunk</h4>
        <span className="text-xs text-muted">不进入模型上下文</span>
      </div>
      <div className="overflow-x-auto">
        <table className="admin-table w-full min-w-[36rem] text-left text-xs">
          <thead>
            <tr>
              <th>来源</th>
              <th>文档</th>
              <th>风险</th>
              <th>分数</th>
              <th>预览</th>
            </tr>
          </thead>
          <tbody>
            {chunks.map((row, idx) => (
              <tr key={`${row.doc_id ?? "x"}-${row.block_index ?? idx}-${idx}`}>
                <td className="align-top whitespace-nowrap">
                  <span className="chip chip-muted">{row.channel || "kb"}</span>
                </td>
                <td className="align-top">
                  <div className="font-medium text-ink">
                    {row.filename || "（未知文件）"}
                  </div>
                  <div className="mt-0.5 font-mono text-[10px] text-muted">
                    {row.doc_id ? shortId(String(row.doc_id)) : "—"}
                    {row.kb_id ? ` · kb ${shortId(String(row.kb_id))}` : ""}
                  </div>
                </td>
                <td className="align-top">
                  <RiskChip risk={String(row.level || "medium")} />
                  <div className="mt-1 flex max-w-[10rem] flex-wrap gap-1">
                    {(row.reasons || []).map((r) => (
                      <span key={r} className="chip chip-muted font-mono text-[10px]">
                        {r}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="align-top tabular-nums text-muted">
                  {typeof row.score === "number" ? row.score.toFixed(3) : "—"}
                </td>
                <td className="align-top max-w-[18rem]">
                  <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted">
                    {row.preview || "—"}
                  </pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TraceIoPreviewButton({
  title,
  subtitle,
  input,
  output,
  metadata,
}: {
  title: string;
  subtitle?: string;
  input?: string | null;
  output?: string | null;
  metadata?: Record<string, unknown> | null;
}) {
  const { openPreview } = usePreviewPanel();
  const hasIo = !!(input || output);
  const hasMetadata = !!metadata && Object.keys(metadata).length > 0;
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      className="mt-1.5"
      onClick={() =>
        openPreview({
          kind: "trace-io",
          title,
          subtitle,
          input,
          output,
          metadata: hasMetadata ? metadata : null,
        })
      }
    >
      预览 IO
      {!hasIo && hasMetadata ? " · meta" : null}
    </Button>
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

function RiskChip({ risk }: { risk: string }) {
  const normalized = risk === "high" || risk === "medium" ? risk : "low";
  if (normalized === "high") {
    return <span className="chip chip-danger">高风险</span>;
  }
  if (normalized === "medium") {
    return <span className="chip chip-warning">中风险</span>;
  }
  return <span className="chip chip-muted">低风险</span>;
}

function metaRisk(metadata: Record<string, unknown> | null | undefined): string {
  const value = metadata?.prompt_injection_risk;
  return typeof value === "string" ? value : "low";
}

function metaSuspiciousCount(
  metadata: Record<string, unknown> | null | undefined
): number {
  const value = metadata?.rag_suspicious_chunks;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function metaReasons(metadata: Record<string, unknown> | null | undefined): string[] {
  const value = metadata?.prompt_injection_reasons;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function metaFilteredChunks(
  metadata: Record<string, unknown> | null | undefined
): FilteredChunkRow[] {
  const value = metadata?.rag_filtered_chunks;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is FilteredChunkRow => !!item && typeof item === "object");
}

function metaPromptVersions(
  metadata: Record<string, unknown> | null | undefined
): PromptVersionEntry[] {
  const entries: PromptVersionEntry[] = [];
  const add = (surface: string, value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const record = value as Record<string, unknown>;
    const key = typeof record.key === "string" ? record.key : null;
    const source = record.source === "registry" ? "registry" : record.source === "code" ? "code" : null;
    if (!key || !source) return;
    entries.push({
      surface,
      key,
      source,
      version: typeof record.version === "number" ? record.version : null,
      digest: typeof record.digest === "string" ? record.digest : null,
    });
  };

  add("回答规则", metadata?.prompt_registry);
  const scope = metadata?.kb_auto_route;
  if (scope && typeof scope === "object" && !Array.isArray(scope)) {
    const scopeRecord = scope as Record<string, unknown>;
    add("运行范围识别", scopeRecord.intent_prompt_registry);
    const route = scopeRecord.kb_route;
    if (route && typeof route === "object" && !Array.isArray(route)) {
      add("知识库自动路由", (route as Record<string, unknown>).prompt_registry);
    }
  }
  return entries;
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
