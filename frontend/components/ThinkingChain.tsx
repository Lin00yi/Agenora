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
const LEGACY_NAME_LABEL: Record<string, string> = {
  search_kb: "检索知识库",
  search_kg: "检索知识图谱",
  web_search: "搜索网络",
  generate_kb_report: "生成知识库报告",
  get_current_time: "获取当前时间",
  intent_ready: "识别任务意图",
  human_input_required: "等待你补充信息",
  dag_ready: "处理计划",
  agent_route: "选择处理方式",
  agent_handoff: "切换处理方式",
  kb_routed: "选择知识库",
};

const AGENT_LABEL: Record<string, string> = {
  chat: "通用对话",
  rag: "知识库问答",
  orders: "订单与退款",
};

const TASK_LABEL: Record<string, string> = {
  qa_kb: "查阅知识库",
  qa_chat: "通用对话",
  qa_orders: "订单与退款",
};

type DagTask = {
  id?: string;
  type?: string;
  agent?: string;
  depends_on?: string[];
};

export function formatDagPlan(tasks: unknown): string {
  if (!Array.isArray(tasks) || tasks.length === 0) return "";
  const labels = tasks.map((raw) => {
    const task = raw as DagTask;
    if (task.type && TASK_LABEL[task.type]) return TASK_LABEL[task.type];
    if (task.agent === "rag") return TASK_LABEL.qa_kb;
    if (task.agent === "chat") return TASK_LABEL.qa_chat;
    return AGENT_LABEL[String(task.agent ?? "")] || "处理";
  });
  return labels.join(" → ");
}

/**
 * Compact processing record for end users.
 * Route/source/confidence stay out of the visible line; agent identity lives
 * in the collapsed summary so expanded rows are not repeated badges.
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
  const visibleEvents = useMemo(() => compactEvents(events), [events]);

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

/** Keep the latest plan; hide internal agent_route once a DAG is shown. */
export function compactEvents(events: ToolEvent[]): ToolEvent[] {
  const latestPlan = [...events].reverse().find((event) => event.name === "dag_ready");
  const out: ToolEvent[] = [];
  let planEmitted = false;
  for (const event of events) {
    if (latestPlan && event.name === "agent_route") continue;
    if (event.name === "dag_ready") {
      if (planEmitted || !latestPlan) continue;
      out.push(latestPlan);
      planEmitted = true;
      continue;
    }
    const prev = out[out.length - 1];
    if (
      event.name === "agent_route" &&
      prev?.name === "agent_route" &&
      String(prev.input?.agent ?? "") === String(event.input?.agent ?? "")
    ) {
      out[out.length - 1] = event;
      continue;
    }
    out.push(event);
  }
  return out;
}

function getTraceSummary(events: ToolEvent[], hasRunning: boolean, elapsedMs: number | null): string {
  const agentHint = latestPlanOrAgentLabel(events);
  if (hasRunning) {
    const active = events.filter((event) => event.status === "running" && !isRouteEvent(event.name));
    if (active.length === 0) {
      return agentHint ? `${agentHint} · 处理中` : "正在处理";
    }
    const labels = new Set(active.map((event) => toolLabel(event)));
    const action =
      labels.size === 1 ? `正在${Array.from(labels)[0]}` : `正在处理 · ${active.length} 项`;
    return agentHint ? `${agentHint} · ${action}` : action;
  }
  if (events.some((event) => event.status === "error" || event.status === "blocked")) {
    const base = elapsedMs == null ? "部分步骤未完成" : `部分步骤未完成 · ${formatElapsed(elapsedMs)}`;
    return agentHint ? `${agentHint} · ${base}` : base;
  }
  const base = elapsedMs == null ? "已处理" : `已处理 ${formatElapsed(elapsedMs)}`;
  return agentHint ? `${agentHint} · ${base}` : base;
}

function latestPlanOrAgentLabel(events: ToolEvent[]): string | null {
  const plan = [...events].reverse().find((event) => event.name === "dag_ready");
  if (plan) {
    const label = formatDagPlan(plan.input?.tasks);
    if (label) return label;
  }
  return latestAgentLabel(events);
}

function latestAgentLabel(events: ToolEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (event.name === "agent_handoff") {
      const to = String(event.input?.to ?? "");
      if (AGENT_LABEL[to]) return AGENT_LABEL[to];
    }
    if (event.name === "agent_route") {
      const agent = String(event.input?.agent ?? "");
      if (AGENT_LABEL[agent]) return AGENT_LABEL[agent];
    }
    if (event.agent && AGENT_LABEL[event.agent]) return AGENT_LABEL[event.agent];
  }
  return null;
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
  if (event.name === "dag_ready") {
    const plan = formatDagPlan(event.input?.tasks);
    return plan || "处理计划";
  }
  if (event.name === "agent_route") {
    const agent = String(event.input?.agent ?? "");
    const label = (AGENT_LABEL[agent] ?? agent) || "处理";
    return `使用${label}`;
  }
  if (event.name === "agent_handoff") {
    const from = AGENT_LABEL[String(event.input?.from ?? "")] ?? String(event.input?.from ?? "");
    const to = AGENT_LABEL[String(event.input?.to ?? "")] ?? String(event.input?.to ?? "");
    if (from && to) return `从${from}转到${to}`;
    return "切换处理方式";
  }
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
  if (event.name === "dag_ready" || event.name === "agent_route" || event.name === "agent_handoff") {
    const reason = typeof event.input?.reason === "string" ? event.input.reason : event.reason;
    return typeof reason === "string" ? formatRouteReason(reason.trim()) : "";
  }
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
  return LEGACY_NAME_LABEL[event.name] ?? "调用服务能力";
}

/** Map machine / LLM snake reasons to short Chinese; hide opaque tokens. */
export function formatRouteReason(reason: string): string {
  if (!reason) return "";
  const exact: Record<string, string> = {
    kb_bound_default: "已绑定知识库",
    unbound_default: "未绑定知识库",
    kb_bound_non_kb_intent: "闲聊或非检索问题",
    kb_bound_chitchat: "闲聊",
    rag_empty_evidence: "知识库暂无相关内容",
    rag_missing_kb_fallback: "知识库暂不可用",
    empty_query_kb_bound: "空问题",
    single_available: "仅一条可用通路",
    first_available: "默认通路",
    needs_kb_fact: "需要查阅知识库",
    needs_kb: "需要查阅知识库",
    kb_fact: "知识库事实问题",
    chitchat: "闲聊",
    general_chat: "通用对话即可",
    web_needed: "需要联网核实",
    needs_kb_then_web: "先查知识库，不够再联网",
    multi_intent: "问题含多个意图",
  };
  if (exact[reason]) return exact[reason];

  const lower = reason.toLowerCase();
  if (lower.includes("query_about") || lower.includes("about_")) return "需要查阅知识库";
  if (lower.includes("chitchat") || lower.includes("greeting")) return "闲聊";
  if (lower.includes("non_kb") || lower.includes("not_kb")) return "非知识库问题";
  if (lower.includes("web") || lower.includes("search")) return "需要联网";
  if (lower.includes("kb") || lower.includes("rag") || lower.includes("fact")) {
    return "需要查阅知识库";
  }
  // Opaque model tokens (snake_case / truncated) stay hidden for end users.
  if (/^[a-z0-9_]+$/i.test(reason) || reason.includes("_") || reason.includes("[")) {
    return "";
  }
  return reason.length > 24 ? `${reason.slice(0, 24)}…` : reason;
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
  return name === "dag_ready" || name === "agent_route" || name === "agent_handoff" || name === "kb_routed";
}

function normalizeIssue(issue: string): string {
  return issue.length > 96 ? `${issue.slice(0, 96)}…` : issue;
}

function truncate(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
