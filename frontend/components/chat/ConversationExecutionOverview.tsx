"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { SpanWaterfall } from "@/components/admin/SpanWaterfall";
import { Button } from "@/components/ui/button";
import {
  getConversationTrace,
  listConversationTraces,
  type ConversationTraceList,
} from "@/lib/conversations-api";
import type { Message } from "@/lib/conversationStore";
import type { TraceDetail, TraceSummary } from "@/lib/trace-types";

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
export function ConversationExecutionOverview({ conversationId }: { conversationId: string | null }) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTraces = useCallback(async () => {
    if (!conversationId) {
      setTraces([]);
      setSelectedTraceId(null);
      setDetail(null);
      setLoadingList(false);
      return;
    }
    setLoadingList(true);
    setError(null);
    try {
      const result: ConversationTraceList = await listConversationTraces(conversationId);
      setTraces(result.traces);
      setSelectedTraceId((current) =>
        current && result.traces.some((trace) => trace.id === current)
          ? current
          : result.traces[0]?.id ?? null
      );
    } catch (cause) {
      setTraces([]);
      setSelectedTraceId(null);
      setDetail(null);
      setError((cause as Error).message || "无法读取本会话的执行链路。");
    } finally {
      setLoadingList(false);
    }
  }, [conversationId]);

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
    return <p aria-live="polite" className="text-pretty text-sm leading-6 text-muted">正在读取执行链路。</p>;
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
      <label className="block space-y-1.5 text-xs">
        <span className="font-medium text-muted">请求记录</span>
        <select
          aria-label="选择请求记录"
          className="admin-input h-[var(--control-h)] w-full"
          value={selectedTraceId ?? ""}
          onChange={(event) => setSelectedTraceId(event.target.value || null)}
        >
          {traces.map((trace, index) => (
            <option key={trace.id} value={trace.id}>
              {traceOptionLabel(trace, traces.length - index)}
            </option>
          ))}
        </select>
      </label>

      {loadingDetail ? (
        <p aria-live="polite" className="text-pretty text-sm leading-6 text-muted">正在读取节点详情。</p>
      ) : detail ? (
        <SpanWaterfall
          nodes={detail.observations}
          totalMs={Math.max(1, detail.duration_ms ?? 0)}
          rootStart={Number.isFinite(rootStart) ? rootStart : 0}
        />
      ) : null}
    </section>
  );
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
