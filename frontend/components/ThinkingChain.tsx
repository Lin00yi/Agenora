"use client";

import { cn } from "@/lib/utils";
import {
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  Search,
  Shuffle,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export type ToolEvent = {
  id?: string;
  name: string;
  input?: Record<string, unknown>;
  status: "running" | "ok" | "error" | "blocked";
  latency_ms?: number | null;
  t0?: number;
  error?: string | null;
  reason?: string;
  /** Sub-agent that owns this step (chat | rag | …). */
  agent?: string;
  /** Host-reviewed display data, normally provided by a dynamic MCP capability. */
  display?: {
    kind?: "mcp";
    label?: string;
    detail?: string;
    server_id?: string;
    capability_id?: string;
    risk?: "read" | "write" | "high_risk_write";
  };
};

type Props = {
  events: ToolEvent[];
  /** Brief public-facing lead-in emitted before this tool wave. */
  intro?: string;
};

// Compatibility only for built-in tools and historical rows created before
// MCP capabilities emitted a reviewed display descriptor. Newly mounted MCP
// tools render from event.display and do not require a frontend release.
const BUILTIN_TOOL_LABEL: Record<string, string> = {
  search_kb: "检索知识库",
  search_kg: "检索知识图谱",
  web_search: "搜索网络",
  generate_kb_report: "生成知识库报告",
  get_current_time: "获取当前时间",
  human_input_required: "等待你补充信息",
};

/**
 * Compact processing record for end users.
 * Historical orchestration stays in the admin Trace; chat shows only actions
 * that are meaningful to the user.
 */
export default function ThinkingChain({ events, intro }: Props) {
  // Supervisor planning/dispatch events are historical runtime details, not
  // user-visible actions.
  const visibleEvents = useMemo(() => compactEvents(events), [events]);
  const hasRunning = visibleEvents.some((event) => event.status === "running");
  const [open, setOpen] = useState(hasRunning);
  const wasRunningRef = useRef(hasRunning);
  const [now, setNow] = useState(() => Date.now());
  const elapsedMs = useTraceElapsed(visibleEvents, now);
  const summary = useMemo(
    () => getTraceSummary(visibleEvents, hasRunning, elapsedMs),
    [visibleEvents, hasRunning, elapsedMs]
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

  if (visibleEvents.length === 0) return null;

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
              {visibleEvents.map((event, index) => (
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
  const Icon = isRouteEvent(event.name) ? Shuffle : isSearchTool(event.name) ? Search : Wrench;
  const detail = formatToolDetail(event);
  const duration = formatEventDuration(event, now);
  const issue = event.error || (isRouteEvent(event.name) ? null : event.reason);

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

/** Remove historical Supervisor orchestration from the end-user timeline. */
export function compactEvents(events: ToolEvent[]): ToolEvent[] {
  return events.filter((event) => !isHistoricalOrchestrationEvent(event.name));
}

function getTraceSummary(events: ToolEvent[], hasRunning: boolean, elapsedMs: number | null): string {
  if (hasRunning) {
    const active = events.filter((event) => event.status === "running" && !isRouteEvent(event.name));
    if (active.length === 0) {
      return "正在处理";
    }
    const labels = new Set(active.map((event) => toolLabel(event)));
    const action =
      labels.size === 1 ? `正在${Array.from(labels)[0]}` : `正在处理 · ${active.length} 项`;
    return action;
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

export function formatToolAction(event: ToolEvent): string {
  if (event.name === "kb_routed") {
    const name = String(event.input?.name ?? "").trim();
    return name ? `本轮检索 ${name}` : "本轮选择知识库";
  }
  const base = toolLabel(event);
  if (event.status === "running") return `正在${base}`;
  if (event.status === "ok") return `已${base}`;
  if (event.status === "blocked") return `${base}已阻止`;
  return `${base}失败`;
}

function formatToolDetail(event: ToolEvent): string {
  const displayDetail = event.display?.detail?.trim();
  if (displayDetail) return truncate(displayDetail, 72);
  const input = event.input;
  if (!input) return "";
  for (const key of ["query", "city", "date", "timezone"] as const) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return truncate(value.trim(), 72);
  }
  return "";
}

function toolLabel(event: ToolEvent): string {
  const dynamic = event.display?.label?.trim();
  if (dynamic) return dynamic;
  return BUILTIN_TOOL_LABEL[event.name] ?? "调用服务能力";
}

function formatEventDuration(event: ToolEvent, now: number): string | null {
  if (isRouteEvent(event.name)) return null;
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

function isRouteEvent(name: string): boolean {
  return name === "kb_routed";
}

function isHistoricalOrchestrationEvent(name: string): boolean {
  return name === "intent_ready" || name === "dag_ready" || name === "agent_route" || name === "agent_handoff";
}

function normalizeIssue(issue: string): string {
  const normalized = issue.trim();
  // Older persisted tool rows used the literal "yes" as an error sentinel.
  // These rows have already discarded the original reason, so make that
  // limitation explicit instead of misleading users with a generic failure.
  if (!normalized || normalized.toLowerCase() === "yes") {
    return "旧记录未保存具体失败原因；请在追踪中查看原始错误。";
  }
  return normalized.length > 160 ? `${normalized.slice(0, 160)}…` : normalized;
}

function truncate(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
