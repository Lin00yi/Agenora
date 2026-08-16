import type { ConversationContextStatus, ConversationSummary, MessagePayload } from "@/lib/conversations-api";
import { joinAssistantText, parseAssistantParts, type Conversation, type Message } from "@/lib/conversationStore";

export const EMPTY_ASSISTANT_RESPONSE =
  "\u672c\u8f6e\u6ca1\u6709\u751f\u6210\u53ef\u5c55\u793a\u5185\u5bb9\uff0c\u8bf7\u91cd\u8bd5\u3002";
export const STOPPED_GENERATION_MESSAGE = "\u7528\u6237\u5df2\u505c\u6b62\u751f\u6210";
export const CONVERSATION_PAGE_SIZE = 30;
export const CHAT_PANE_FADE_MS = 180;

const DEFAULT_CONTEXT_WINDOW = 16_000;
const CONTEXT_WINDOWS: Record<string, number> = {
  // Kept temporarily for conversations that have not yet been opened since
  // the backend startup migration; new DeepSeek calls use the V4 models.
  "deepseek-chat": 64_000,
  "deepseek-reasoner": 64_000,
  "deepseek-v4-flash": 1_000_000,
  "deepseek-v4-pro": 1_000_000,
  "gpt-4o": 128_000,
  "gpt-4o-mini": 128_000,
  "claude-haiku-4-5-20251001": 200_000,
  "claude-sonnet-4-6": 200_000,
  "claude-opus-4-7": 200_000,
};
const CONTEXT_OUTPUT_RESERVE = 2_048;
const CONTEXT_SYSTEM_TOOL_RESERVE = 6_000;
const CONTEXT_RAG_RESERVE = 8_000;
const CONTEXT_SAFETY_RESERVE = 2_000;

export function getContextWindowForModel(model: string | null, fallbackModels: string[] = []) {
  if (model) return CONTEXT_WINDOWS[model] ?? DEFAULT_CONTEXT_WINDOW;
  const fallbackWindow = Math.max(
    ...fallbackModels.map((candidate) => CONTEXT_WINDOWS[candidate] ?? DEFAULT_CONTEXT_WINDOW),
    DEFAULT_CONTEXT_WINDOW
  );
  return fallbackWindow;
}

export function estimateContextStatus(
  messages: Message[],
  model: string | null,
  fallbackModels: string[] = [],
  kbId: string | null = null
): ConversationContextStatus {
  const window = getContextWindowForModel(model, fallbackModels);
  const ragReserve = kbId ? CONTEXT_RAG_RESERVE : 0;
  const available = Math.max(
    4_000,
    window -
      CONTEXT_OUTPUT_RESERVE -
      CONTEXT_SYSTEM_TOOL_RESERVE -
      ragReserve -
      CONTEXT_SAFETY_RESERVE
  );
  const current = messages.reduce((total, message) => {
    const content =
      message.role === "assistant"
        ? joinAssistantText(message.parts, message.content)
        : message.content ?? "";
    const cjk = [...content].filter((char) => char >= "\u4e00" && char <= "\u9fff").length;
    return total + Math.max(1, Math.floor(cjk * 1.2 + Math.max(content.length - cjk, 0) / 3.2)) + 6;
  }, 0);
  const ratio = current / available;
  const percent = Math.min(100, Math.round(ratio * 100));
  const state =
    ratio >= 0.85 ? "critical" : ratio >= 0.72 ? "ready" : ratio >= 0.6 ? "approaching" : "normal";

  return {
    state,
    label: "本地估算",
    description: `后端尚未提供上下文状态，已按当前消息和 ${model ?? "默认模型"} 的上下文窗口估算。`,
    current_tokens: current,
    raw_history_tokens: current,
    available_tokens: available,
    context_window: window,
    ratio,
    percent,
    prepare_threshold_percent: 60,
    summary_threshold_percent: 72,
    force_threshold_percent: 85,
    retained_recent_turns: 10,
    summary: null,
  };
}

export function conversationHref(id: string) {
  return `/c/${encodeURIComponent(id)}`;
}

export function conversationIdFromPath(pathname: string) {
  const match = pathname.match(/^\/c\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

export function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => !!value)));
}

/**
 * Parse API timestamps as instants.  Conversation timestamps are stored in
 * UTC; old SQLite responses omitted the UTC offset, so retain compatibility
 * by treating those legacy values as UTC rather than as browser-local time.
 */
export function parseServerTimestamp(value: string | null | undefined): number {
  if (!value) return Date.now();
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const normalized = hasOffset ? value : `${value}Z`;
  const parsed = new Date(normalized).getTime();
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

function isRenderableMessage(message: Message) {
  if (message.role === "user") return true;
  const hasRenderableTimelinePart = message.parts?.some(
    (part) =>
      (part.type === "text" && part.text.trim().length > 0) ||
      (part.type === "tools" && part.tools.length > 0)
  );
  return Boolean(
    message.streaming ||
      message.error ||
      message.content.trim().length > 0 ||
      hasRenderableTimelinePart ||
      message.tools.length > 0
  );
}

export function normalizeMessages(messages: Message[]) {
  return messages.filter(isRenderableMessage);
}

export function serverMsgToLocal(m: MessagePayload): Message {
  const ts = parseServerTimestamp(m.created_at);
  if (m.role === "user") {
    return { id: m.id, role: "user", content: m.content, created_at: ts };
  }
  const parts = parseAssistantParts(m.parts);
  return {
    id: m.id,
    role: "assistant",
    // `content` is the canonical full text stored for prompt context. Once a
    // persisted timeline is present, render from its text segments instead to
    // avoid duplicating that canonical text below the timeline.
    content: parts ? "" : m.content,
    tools: m.tools ?? [],
    parts,
    memory_trace: m.memory_trace ?? null,
    citations: m.citations ?? null,
    cost_usd: m.cost_usd ?? undefined,
    error: m.error === STOPPED_GENERATION_MESSAGE ? undefined : m.error ?? undefined,
    created_at: ts,
  };
}

export function summaryToConv(s: ConversationSummary, messages: Message[] = []): Conversation {
  const createdMs = parseServerTimestamp(s.created_at);
  const updatedMs = s.updated_at ? parseServerTimestamp(s.updated_at) : createdMs;
  const finalizedMs = s.finalized_at ? parseServerTimestamp(s.finalized_at) : null;
  return {
    id: s.id,
    title: s.title,
    messages,
    kb_id: s.kb_id,
    llm_model: s.llm_model,
    message_count: s.message_count,
    created_at: createdMs,
    updated_at: updatedMs,
    finalized_at: finalizedMs,
  };
}

export function mergeConversationSummaries(
  current: ConversationSummary[],
  incoming: ConversationSummary[]
) {
  const seen = new Set<string>();
  return [...current, ...incoming].filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

export function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function waitPaneMs(ms: number) {
  if (prefersReducedMotion() || ms <= 0) return Promise.resolve();
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}
