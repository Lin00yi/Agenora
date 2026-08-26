"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { SpanWaterfall, type TraceNodePreview } from "@/components/admin/SpanWaterfall";
import Select from "@/components/Select";
import { Button } from "@/components/ui/button";
import {
  getConversationTrace,
  listConversationTraces,
  type ConversationTraceList,
} from "@/lib/conversations-api";
import type { Message } from "@/lib/conversationStore";
import type { TraceDetail, TraceSummary } from "@/lib/trace-types";

const TRACE_PAGE_SIZE = 50;

/** Optimistic visibility check while the durable Trace query is loading. */
export function hasConversationExecutionData(messages: Message[]) {
  return messages.some(
    (message) =>
      message.role === "assistant" &&
      (message.tools.length > 0 ||
        message.memory_trace?.runtime?.execution != null ||
        message.memory_trace?.runtime?.ttft_ms != null ||
        message.streaming === true)
  );
}

/**
 * Conversation-scoped view of the exact persisted Trace / Observation tree.
 * It intentionally shares SpanWaterfall with the admin Trace page so the node
 * tree, timing bars, TTFT and node inspection cannot drift between surfaces.
 */
export function ConversationExecutionOverview({
  conversationId,
  onNodePreview,
}: {
  conversationId: string | null;
  onNodePreview?: (preview: TraceNodePreview | null) => void;
}) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tracesRef = useRef<TraceSummary[]>([]);
  const selectedTraceIdRef = useRef<string | null>(null);

  useEffect(() => {
    selectedTraceIdRef.current = selectedTraceId;
  }, [selectedTraceId]);

  const loadTraces = useCallback(
    async (
      {
        append = false,
        offset = 0,
      }: { append?: boolean; offset?: number } = {}
    ) => {
      if (!conversationId) {
        tracesRef.current = [];
        setTraces([]);
        setSelectedTraceId(null);
        onNodePreview?.(null);
        setDetail(null);
        setTotal(0);
        setHasMore(false);
        setLoadingList(false);
        return;
      }
      if (append) setLoadingMore(true);
      else setLoadingList(true);
      setError(null);
      try {
        const result: ConversationTraceList = await listConversationTraces(conversationId, {
          limit: TRACE_PAGE_SIZE,
          offset,
        });
        setTotal(result.total);
        setHasMore(result.has_more);
        const next = append
          ? mergeTraces(tracesRef.current, result.traces)
          : result.traces;
        tracesRef.current = next;
        setTraces(next);
        const selected = selectedTraceIdRef.current;
        const nextSelected =
          selected && next.some((trace) => trace.id === selected)
            ? selected
            : next[0]?.id ?? null;
        if (nextSelected !== selected) onNodePreview?.(null);
        setSelectedTraceId(nextSelected);
      } catch (cause) {
        setTraces([]);
        setSelectedTraceId(null);
        setDetail(null);
        setError((cause as Error).message || "无法读取本会话的执行链路。");
      } finally {
        setLoadingList(false);
        setLoadingMore(false);
      }
    },
    [conversationId, onNodePreview]
  );

  useEffect(() => {
    void loadTraces();
  }, [loadTraces]);

  useEffect(() => {
    if (!conversationId || !selectedTraceId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    setError(null);
    void getConversationTrace(conversationId, selectedTraceId)
      .then((next) => {
        if (!cancelled) setDetail(next);
      })
      .catch((cause: Error) => {
        if (!cancelled) {
          setDetail(null);
          setError(cause.message || "无法读取该轮执行链路。");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, selectedTraceId]);

  const rootStart = detail?.started_at ? Date.parse(detail.started_at) : 0;

  if (loadingList) {
    return (
      <p aria-live="polite" className="text-pretty text-sm leading-6 text-muted">
        正在读取执行链路。
      </p>
    );
  }

  if (error) {
    return (
      <div role="alert" className="space-y-3">
        <p className="text-pretty text-sm leading-6 text-danger">读取执行链路失败：{error}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void loadTraces()}>
          <RefreshCw className="size-4" aria-hidden />
          重新读取
        </Button>
      </div>
    );
  }

  if (traces.length === 0) {
    return (
      <p className="text-pretty text-sm leading-6 text-muted">
        此会话暂时没有已持久化的执行链路。
      </p>
    );
  }

  return (
    <section aria-label="执行链路详情" className="min-h-0 space-y-4">
      <div className="flex items-end gap-2">
        <label className="min-w-0 flex-1 space-y-1.5 text-xs">
          <span className="font-medium text-muted">请求记录，共 {total} 条</span>
          <Select
            aria-label="选择请求记录"
            value={selectedTraceId ?? ""}
            onChange={(event) => {
              onNodePreview?.(null);
              setSelectedTraceId(event.target.value || null);
            }}
            options={traces.map((trace, index) => ({
              value: trace.id,
              label: traceOptionLabel(trace, total - index),
            }))}
          />
        </label>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="刷新执行链路"
          title="刷新执行链路"
          onClick={() => void loadTraces()}
        >
          <RefreshCw className="size-4" aria-hidden />
        </Button>
      </div>

      {loadingDetail ? (
        <p aria-live="polite" className="text-pretty text-sm leading-6 text-muted">
          正在读取节点详情。
        </p>
      ) : detail ? (
        <SpanWaterfall
          nodes={detail.observations}
          totalMs={Math.max(1, detail.duration_ms ?? 0)}
          rootStart={Number.isFinite(rootStart) ? rootStart : 0}
          onNodePreview={onNodePreview}
        />
      ) : null}

      {hasMore ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loadingMore}
          onClick={() => void loadTraces({ append: true, offset: traces.length })}
        >
          {loadingMore ? "正在加载" : "加载更早记录"}
        </Button>
      ) : null}
    </section>
  );
}

function mergeTraces(current: TraceSummary[], incoming: TraceSummary[]): TraceSummary[] {
  const seen = new Set<string>();
  const merged: TraceSummary[] = [];
  for (const trace of [...current, ...incoming]) {
    if (seen.has(trace.id)) continue;
    seen.add(trace.id);
    merged.push(trace);
  }
  return merged;
}

function traceOptionLabel(trace: TraceSummary, turn: number): string {
  const duration = trace.duration_ms == null ? "—" : formatDuration(trace.duration_ms);
  const state = trace.status === "error" ? "失败" : trace.status === "ok" ? "成功" : trace.status;
  return `第 ${turn} 轮 · ${state} · ${duration}`;
}

function formatDuration(value: number): string {
  if (value < 1_000) return `${Math.round(value)} ms`;
  return `${(value / 1_000).toFixed(2)} s`;
}
