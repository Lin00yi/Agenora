"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  Search,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type ToolEvent = {
  id?: string;
  name: string;
  input?: Record<string, unknown>;
  status: "running" | "ok" | "error" | "blocked";
  latency_ms?: number | null;
  t0?: number;
  error?: string | null;
  reason?: string;
};

type Props = {
  events: ToolEvent[];
  /** Brief public-facing lead-in emitted before this tool wave. */
  intro?: string;
};

const NAME_LABEL: Record<string, string> = {
  search_kb: "检索知识库",
  search_kg: "检索知识图谱",
  web_search: "搜索网络",
  generate_kb_report: "生成知识库报告",
  get_current_time: "获取当前时间",
};

/**
 * A compact, GPT-style processing record. It intentionally avoids the old
 * nested-card treatment: the answer remains the visual focus, while users can
 * expand a truthful, chronological account of the visible tool actions.
 */
export default function ThinkingChain({ events, intro }: Props) {
  const hasRunning = events.some((event) => event.status === "running");
  const [open, setOpen] = useState(hasRunning);
  const wasRunningRef = useRef(hasRunning);
  const [now, setNow] = useState(() => Date.now());
  const elapsedMs = useTraceElapsed(events, now);
  const summary = useMemo(
    () => getTraceSummary(events, hasRunning, elapsedMs),
    [events, hasRunning, elapsedMs]
  );

  useEffect(() => {
    if (hasRunning) {
      setOpen(true);
      wasRunningRef.current = true;
      return;
    }
    if (wasRunningRef.current) {
      setOpen(false);
      wasRunningRef.current = false;
    }
  }, [hasRunning]);

  useEffect(() => {
    if (!hasRunning) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [hasRunning]);

  return (
    <section aria-label="处理过程" className="py-1 text-sm">
      <button
        aria-expanded={open}
        className="flex min-h-8 items-center gap-2 text-left text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        {hasRunning ? (
          <LoaderCircle
            aria-hidden="true"
            className="size-4 shrink-0 animate-spin motion-reduce:animate-none"
          />
        ) : open ? (
          <ChevronDown aria-hidden="true" className="size-4 shrink-0" />
        ) : (
          <ChevronRight aria-hidden="true" className="size-4 shrink-0" />
        )}
        <span aria-live="polite" className="text-sm">
          {summary}
        </span>
      </button>

      <div className={cn("mt-2 border-t border-surface-border/60", open && "pt-3")}>
        {open ? (
          <>
            {intro ? (
              <p className="mb-4 whitespace-pre-wrap text-pretty leading-7 text-ink/85">{intro}</p>
            ) : null}
            <ol className="space-y-2.5" aria-label="处理步骤">
              {events.map((event, index) => (
                <ProcessEvent event={event} key={event.id ?? `${event.name}-${index}`} now={now} />
              ))}
            </ol>
          </>
        ) : null}
      </div>
    </section>
  );
}

function ProcessEvent({ event, now }: { event: ToolEvent; now: number }) {
  const Icon = isSearchTool(event.name) ? Search : Wrench;
  const detail = formatToolDetail(event);
  const duration = formatEventDuration(event, now);
  const issue = event.error || event.reason;

  return (
    <li className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 shrink-0 text-muted" aria-hidden="true">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className={event.status === "error" ? "text-red-500" : "text-muted"}>
            {formatToolAction(event)}
          </span>
          {detail ? <span className="truncate text-muted/80">{detail}</span> : null}
          {duration ? <span className="text-xs tabular-nums text-muted/70">{duration}</span> : null}
        </div>
        {issue ? (
          <p className={event.status === "blocked" ? "mt-1 text-xs text-amber-600" : "mt-1 text-xs text-red-500"}>
            {normalizeIssue(issue)}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function getTraceSummary(events: ToolEvent[], hasRunning: boolean, elapsedMs: number | null): string {
  if (hasRunning) {
    const active = events.filter((event) => event.status === "running");
    const labels = new Set(active.map((event) => NAME_LABEL[event.name] ?? "处理信息"));
    if (labels.size === 1) return `正在${Array.from(labels)[0]}`;
    return `正在处理 · ${active.length} 项`;
  }
  if (events.some((event) => event.status === "error" || event.status === "blocked")) {
    return elapsedMs == null ? "部分步骤未完成" : `部分步骤未完成 · ${formatElapsed(elapsedMs)}`;
  }
  return elapsedMs == null ? "已处理" : `已处理 ${formatElapsed(elapsedMs)}`;
}

function useTraceElapsed(events: ToolEvent[], now: number): number | null {
  const startedAt = Math.min(...events.map((event) => event.t0 ?? Number.POSITIVE_INFINITY));
  if (!Number.isFinite(startedAt)) return null;
  const hasRunning = events.some((event) => event.status === "running");
  const completedAt = Math.max(
    ...events.map((event) =>
      event.t0 != null && event.latency_ms != null ? event.t0 + event.latency_ms : event.t0 ?? startedAt
    )
  );
  return Math.max(0, (hasRunning ? now : completedAt) - startedAt);
}

function formatToolAction(event: ToolEvent): string {
  const base = NAME_LABEL[event.name] ?? "处理信息";
  if (event.status === "running") return `正在${base}`;
  if (event.status === "ok") return `已${base}`;
  if (event.status === "blocked") return `${base}已阻止`;
  return `${base}失败`;
}

function formatToolDetail(event: ToolEvent): string {
  const input = event.input;
  if (!input) return "";
  for (const key of ["query", "city", "date", "timezone"] as const) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return truncate(value.trim(), 72);
  }
  return "";
}

function formatEventDuration(event: ToolEvent, now: number): string | null {
  if (event.status === "running" && event.t0 != null) return formatElapsed(now - event.t0);
  if (event.latency_ms != null) return formatElapsed(event.latency_ms);
  return null;
}

function formatElapsed(ms: number): string {
  return `${Math.max(1, Math.round(Math.max(0, ms) / 1000))} 秒`;
}

function isSearchTool(name: string): boolean {
  return name === "search_kb" || name === "search_kg" || name === "web_search";
}

function normalizeIssue(issue: string): string {
  return issue.length > 96 ? `${issue.slice(0, 96)}…` : issue;
}

function truncate(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
