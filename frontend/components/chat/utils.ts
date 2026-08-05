import type { ToolEvent } from "@/components/ThinkingChain";
import type { Conversation, Message } from "@/lib/conversationStore";
import type { KB } from "@/lib/kb-api";
import type { ChatEvent, MemoryTrace, MemoryTraceItem } from "@/lib/sseClient";
import type { SourceRow } from "./types";

export function getKbStatusView(kb: KB) {
  const counts = kb.document_status_counts;
  const failed = counts?.failed ?? 0;
  const running = (counts?.pending ?? 0) + (counts?.ingesting ?? 0);
  if (failed > 0) {
    return {
      label: "\u9700\u5904\u7406",
      detail: `${failed} \u4e2a\u6587\u6863\u5f02\u5e38`,
      dot: "bg-red-400",
      tone: "text-red-300",
    };
  }
  if (running > 0) {
    return {
      label: "\u5904\u7406\u4e2d",
      detail: `${running} \u4e2a\u6587\u6863\u6392\u961f/\u89e3\u6790`,
      dot: "bg-amber-300",
      tone: "text-amber-200",
    };
  }
  if (kb.documents_count === 0) {
    return {
      label: "\u7a7a\u5e93",
      detail: "\u7b49\u5f85\u4e0a\u4f20\u8d44\u6599",
      dot: "kf-status-dot-muted",
      tone: "kf-status-text-muted",
    };
  }
  if (kb.chunks_count > 0) {
    return {
      label: "\u53ef\u68c0\u7d22",
      detail: `${kb.chunks_count.toLocaleString()} 分块`,
      dot: "kf-status-dot-accent",
      tone: "kf-status-text-accent",
    };
  }
  return {
    label: "\u5f85\u7d22\u5f15",
    detail: `${kb.documents_count.toLocaleString()} \u4e2a\u6587\u6863`,
    dot: "kf-status-dot-accent",
    tone: "kf-status-text-accent",
  };
}

export function formatConversationTime(value?: number | null) {
  if (!value) return "";
  const diff = Date.now() - value;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "\u521a\u521a";
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} \u5206\u949f\u524d`;
  if (diff < day) return `${Math.floor(diff / hour)} \u5c0f\u65f6\u524d`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} \u5929\u524d`;
  return new Date(value).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export function getConversationStatusView(conversation: Conversation, currentId: string | null, busy: boolean) {
  const active = conversation.id === currentId;
  const messageCount = conversation.messages.length || conversation.message_count || 0;
  if (active && busy) {
    return {
      label: "\u751f\u6210\u4e2d",
      dot: "bg-amber-300",
      tone: "border-amber-300/20 bg-amber-300/10 text-amber-200",
    };
  }
  if (active) {
    return {
      label: "\u5f53\u524d",
      dot: "kf-status-dot-accent",
      tone: "kf-status-badge-current",
    };
  }
  if (messageCount === 0) {
    return {
      label: "\u7a7a\u4f1a\u8bdd",
      dot: "kf-status-dot-muted",
      tone: "kf-sidebar-status-muted",
    };
  }
  return {
    label: "\u5df2\u4fdd\u5b58",
    dot: "kf-status-dot-accent",
    tone: "kf-status-badge-saved",
  };
}

export function getAssistantStreamingStatus(
  message: Extract<Message, { role: "assistant" }>,
  elapsedMs: number
) {
  const hasContent = message.content.trim().length > 0;
  const hasTools = message.tools.length > 0;
  const toolsRunning = message.tools.some((tool) => tool.status === "running");
  const allToolsSettled = hasTools && !toolsRunning;
  const latestToolDoneAt = getLatestToolDoneAt(message.tools);
  const waitAfterToolsMs =
    allToolsSettled && latestToolDoneAt != null ? Math.max(0, Date.now() - latestToolDoneAt) : null;

  if (hasContent) {
    return { label: "正在生成回答", elapsed: `耗时 ${formatDuration(elapsedMs)}` };
  }
  if (allToolsSettled) {
    return {
      label: "工具完成，正在生成回答",
      elapsed:
        waitAfterToolsMs == null
          ? `耗时 ${formatDuration(elapsedMs)}`
          : `等待 ${formatDuration(waitAfterToolsMs)} / 耗时 ${formatDuration(elapsedMs)}`,
    };
  }
  if (hasTools) {
    return { label: "正在检索知识库", elapsed: `耗时 ${formatDuration(elapsedMs)}` };
  }
  return { label: "正在检索并生成回答", elapsed: `耗时 ${formatDuration(elapsedMs)}` };
}

export function getLatestToolDoneAt(tools: ToolEvent[]) {
  return tools.reduce<number | null>((latest, tool) => {
    if (tool.status === "running" || tool.t0 == null || tool.latency_ms == null) return latest;
    const doneAt = tool.t0 + tool.latency_ms;
    return latest == null ? doneAt : Math.max(latest, doneAt);
  }, null);
}

export function buildMessageSources(message: Extract<Message, { role: "assistant" }>): SourceRow[] {
  if (message.tools.length === 0) return [];
  return aggregateToolSources(message.tools, 4);
}

export function updateToolEvent(
  tools: ToolEvent[],
  evt: ChatEvent,
  patch: Partial<ToolEvent>
): ToolEvent[] {
  const index = findToolEventIndex(tools, evt);
  if (index < 0) return tools;
  return tools.map((tool, i) => (i === index ? { ...tool, ...patch } : tool));
}

export function findToolEventIndex(tools: ToolEvent[], evt: ChatEvent): number {
  if (evt.id) {
    const byId = tools.findIndex((tool) => tool.id === evt.id);
    if (byId >= 0) return byId;
  }
  for (let i = tools.length - 1; i >= 0; i--) {
    if (tools[i].name === evt.name && tools[i].status === "running") return i;
  }
  return -1;
}

export function aggregateToolSources(tools: ToolEvent[], maxRows: number): SourceRow[] {
  const groups = new Map<string, ToolEvent[]>();
  for (const tool of tools) {
    groups.set(tool.name, [...(groups.get(tool.name) ?? []), tool]);
  }
  return Array.from(groups.entries())
    .slice(0, maxRows)
    .map(([name, group]) => buildToolSourceRow(name, group));
}

export function buildToolSourceRow(name: string, group: ToolEvent[]): SourceRow {
  if (group.length === 1) {
    const tool = group[0];
    return {
      title: getToolLabelClean(tool.name),
      meta: getToolMetaClean(tool),
      score: getToolStatusLabelClean(tool.status),
    };
  }

  const status = getAggregateToolStatus(group);
  const slowest = group.reduce<number | null>((max, tool) => {
    if (tool.latency_ms == null) return max;
    return max == null ? tool.latency_ms : Math.max(max, tool.latency_ms);
  }, null);
  const querySummaries = group.map(getToolInputSummary).filter(Boolean).slice(0, 3);
  const action = name === "search_kb" ? "\u67e5\u8be2" : "\u8c03\u7528";
  const duration = slowest == null ? "" : ` \u00b7 \u6700\u6162 ${formatDuration(slowest)}`;

  return {
    title: getToolLabelClean(name),
    meta: `${group.length} \u6b21${action} \u00b7 ${getAggregateToolMeta(status)}${duration}`,
    score: getToolStatusLabelClean(status),
    detail: querySummaries.length > 0 ? querySummaries : undefined,
  };
}

export function getAggregateToolStatus(group: ToolEvent[]): ToolEvent["status"] {
  if (group.some((tool) => tool.status === "running")) return "running";
  if (group.some((tool) => tool.status === "error")) return "error";
  if (group.some((tool) => tool.status === "blocked")) return "blocked";
  return "ok";
}

export function getAggregateToolMeta(status: ToolEvent["status"]) {
  if (status === "ok") return "\u5168\u90e8\u5b8c\u6210";
  if (status === "running") return "\u6b63\u5728\u6267\u884c";
  if (status === "blocked") return "\u90e8\u5206\u963b\u585e";
  return "\u90e8\u5206\u5931\u8d25";
}

export function getToolInputSummary(tool: ToolEvent): string {
  const query = tool.input?.query;
  if (typeof query === "string" && query.trim()) return query.trim();
  const city = tool.input?.city;
  if (typeof city === "string" && city.trim()) return city.trim();
  return "";
}

export function getToolLabelClean(name: string): string {
  const labels: Record<string, string> = {
    search_kb: "\u77e5\u8bc6\u5e93\u68c0\u7d22",
    generate_kb_report: "\u77e5\u8bc6\u5e93\u62a5\u544a",
    web_search: "\u7f51\u7edc\u641c\u7d22",
    get_weather: "\u5929\u6c14\u67e5\u8be2",
    search_restaurant_kb: "\u672c\u5730\u77e5\u8bc6\u68c0\u7d22",
    amap_search: "\u5730\u56fe\u641c\u7d22",
    generate_travel_report: "\u65c5\u884c\u62a5\u544a",
  };
  return labels[name] ?? name;
}

export function getToolStatusLabelClean(status: ToolEvent["status"]) {
  if (status === "ok") return "\u5b8c\u6210";
  if (status === "running") return "\u8fdb\u884c\u4e2d";
  if (status === "blocked") return "\u963b\u585e";
  return "\u5931\u8d25";
}

export function getToolMetaClean(tool: ToolEvent) {
  if (tool.status === "running") return "\u6b63\u5728\u6267\u884c";
  if (tool.status === "ok") {
    return tool.latency_ms ? `\u5df2\u5b8c\u6210 \u00b7 ${formatDuration(tool.latency_ms)}` : "\u5df2\u5b8c\u6210";
  }
  if (tool.status === "blocked") return tool.reason || "\u8c03\u7528\u88ab\u7b56\u7565\u963b\u6b62";
  return normalizeToolError(tool.error);
}

export function normalizeToolError(error?: string | null) {
  if (!error) return "\u8c03\u7528\u5931\u8d25";
  const lower = error.toLowerCase();
  if (lower.includes("timed out") || lower.includes("timeout")) {
    return "\u8bf7\u6c42\u8d85\u65f6\uff0c\u5df2\u8df3\u8fc7\u8be5\u7ed3\u679c";
  }
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("request")) {
    return "\u7f51\u7edc\u8bf7\u6c42\u5931\u8d25\uff0c\u5df2\u8df3\u8fc7\u8be5\u7ed3\u679c";
  }
  return error.length > 48 ? `${error.slice(0, 48)}...` : error;
}

export function formatDuration(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

export function hasVisibleMemoryTrace(trace?: MemoryTrace | null) {
  if (!trace) return false;
  return Boolean(
    trace.profile?.injected ||
      (trace.memories?.injected_count ?? 0) > 0 ||
      trace.summary ||
      (trace.profile?.items?.length ?? 0) > 0 ||
      (trace.memories?.items?.length ?? 0) > 0
  );
}

/** Deduped list of memories actually injected this turn (profile + recall). */
export function buildInjectedMemoryItems(trace: MemoryTrace): MemoryTraceItem[] {
  const seenIds = new Set<string>();
  const seenKeys = new Set<string>();
  const seenContent = new Set<string>();
  const out: MemoryTraceItem[] = [];

  const push = (item: MemoryTraceItem) => {
    const key = (item.key || "").trim();
    const norm = item.content.trim().toLowerCase().replace(/\s+/g, "");
    if (seenIds.has(item.id)) return;
    if (key && seenKeys.has(key)) return;
    if (norm && seenContent.has(norm)) return;
    seenIds.add(item.id);
    if (key) seenKeys.add(key);
    if (norm) seenContent.add(norm);
    out.push(item);
  };

  for (const item of trace.profile?.items ?? []) push(item);
  for (const item of trace.memories?.items ?? []) push(item);
  return out;
}

export function formatMemoryTraceSummary(trace: MemoryTrace): string {
  const items = buildInjectedMemoryItems(trace);
  const parts: string[] = [];

  if (items.length > 0) {
    parts.push(items.length === 1 ? "用了 1 条记忆" : `用了 ${items.length} 条记忆`);
    const hints = Array.from(
      new Set(items.slice(0, 3).map((item) => memoryTraceTypeLabel(item.type)))
    );
    if (hints.length > 0) parts.push(hints.join(" · "));
  }
  if (trace.summary) {
    parts.push("含会话摘要");
  }
  return parts.join(" · ") || "本轮上下文";
}

export function memoryTraceTypeLabel(type: string) {
  if (type === "preference") return "偏好";
  if (type === "constraint") return "约束";
  if (type === "fact") return "事实";
  if (type === "explicit") return "显式";
  return type;
}

export function formatTokenCount(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

/** Format context usage for display. Sub-1% values keep one decimal so a
 * million-token window does not read as a broken "0%" meter. */
export function formatContextUsagePercent(percent: number): string {
  if (!Number.isFinite(percent) || percent <= 0) return "0";
  const clamped = Math.min(100, percent);
  if (clamped < 1) return clamped.toFixed(1);
  return String(Math.round(clamped));
}

/** Precise usage percent from API ratio when present, else integer percent. */
export function resolveContextUsagePercent(status: {
  percent?: number;
  ratio?: number;
  current_tokens?: number;
}): number {
  if (typeof status.ratio === "number" && Number.isFinite(status.ratio)) {
    return Math.min(100, Math.max(0, status.ratio * 100));
  }
  if (typeof status.percent === "number" && Number.isFinite(status.percent)) {
    return Math.min(100, Math.max(0, status.percent));
  }
  return 0;
}

export function formatMessageStats(messages: Message[]) {
  const userCount = messages.filter((message) => message.role === "user").length;
  const assistantCount = messages.filter((message) => message.role === "assistant").length;
  return `${userCount} \u8f6e \u00b7 ${messages.length} \u6761`;
}

export function formatTime(value?: number | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}

export function formatMessageTime(value?: number | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}
