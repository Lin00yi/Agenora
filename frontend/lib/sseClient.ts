export type MemoryTraceItem = {
  id: string;
  scope: string;
  scope_id: string | null;
  type: string;
  key: string | null;
  content: string;
  source: string;
  confidence: number;
  importance: number;
  updated_at: string | null;
};

export type MemoryTrace = {
  /** Safe runtime metadata; raw prompts, schemas, and guard reasons stay server-only. */
  runtime?: {
    mode?: "general" | "knowledge_base";
    agent_runtime?: string;
    safety?: "standard" | "heightened";
  };
  kb_route?: {
    needs_retrieval: boolean;
    selected_kb_id: string | null;
    selected_kb_ids?: string[];
    source: "disabled" | "rule" | "llm" | "fallback";
    confidence: "high" | "medium" | "low";
    reason: string;
    latency_ms: number;
    candidate_count: number;
  };
  profile?: {
    injected: boolean;
    counts?: {
      preferences?: number;
      constraints?: number;
      facts?: number;
      total?: number;
    };
    items?: MemoryTraceItem[];
  };
  memories?: {
    injected_count: number;
    items: MemoryTraceItem[];
  };
  summary?: {
    id: string;
    covered_message_count: number;
    token_count: number;
    updated_at: string | null;
  } | null;
  recent_message_count?: number;
  /** Measured final provider request budget; never contains prompt text or schemas. */
  prompt?: {
    model: string;
    context_window: number;
    tokens: {
      system: number;
      tools: number;
      rag: number;
      history: number;
      output: number;
      safety: number;
      total_input: number;
      profile?: number;
      memory?: number;
      summary?: number;
    };
    truncation: {
      rag: boolean;
      history: boolean;
      profile?: boolean;
      memory?: boolean;
      summary?: boolean;
    };
    retrieval?: {
      mode: "user_evidence" | "legacy_system";
      evidence_count: number;
      source_counts: Record<string, number>;
      in_system: boolean;
      pinned_current_question: boolean;
      status?: "empty" | "miss" | "hit";
      candidate_count?: number;
      admitted_count?: number;
      max_score?: number;
      min_dense_score?: number;
    };
    cache?: {
      system_retrieval_free: boolean;
      system_prefix_tokens: number;
      cache_read_tokens: number;
      cache_creation_tokens: number;
    };
  };
};

/** Structured evidence card from search_kb / web_search (not LLM prose). */
export type Citation = {
  channel: "kb" | "web";
  title: string;
  source: string;
  score?: number | null;
  url?: string | null;
  snippet?: string | null;
  kb_id?: string | null;
  doc_id?: string | null;
};

export type ChatEvent = {
  event:
    | "context_ready"
    | "kb_routed"
    | "agent_route"
    | "agent_handoff"
    | "intent_ready"
    | "human_input_required"
    | "dag_ready"
    | "tool_start"
    | "tool_end"
    | "tool_blocked"
    | "segment_seal"
    | "report_start"
    | "token"
    | "done"
    | "error";
  name?: string;
  id?: string;
  input?: Record<string, unknown>;
  text?: string;
  latency_ms?: number;
  ok?: boolean;
  error?: string;
  reason?: string;
  /** Sub-agent that emitted this tool event (chat | rag | …). */
  agent?: string;
  /** agent_route / agent_handoff targets */
  from?: string;
  to?: string;
  source?: string;
  confidence?: string;
  metadata?: Record<string, unknown>;
  prompt?: string;
  slot?: string;
  required_slots?: string[];
  approval_id?: string;
  confirmation_phrase?: string;
  order_id?: string;
  amount_minor?: number;
  currency?: string;
  interrupted?: boolean;
  /** `turn` is automatic for this response only; `pinned` is a conversation scope. */
  scope?: "turn" | "pinned";
  tasks?: Array<{
    id?: string;
    type?: string;
    agent?: string;
    depends_on?: string[];
  }>;
  cost_usd?: number;
  memory_trace?: MemoryTrace | null;
  citations?: Citation[] | null;
  message?: string;
  kb_id?: string | null;
  kb_ids?: string[];
  /** v2-M2 BYOK gate: `llm_not_configured` | `embedding_not_configured` */
  code?: string;
  retry_after_seconds?: number;
  /** Where the UI should send the user when code is set. */
  settings_url?: string;
};

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
};

import { getToken, handleSessionExpired } from "@/lib/auth";

/**
 * POST /api/chat with full message history and stream the SSE response.
 *
 * Auth: Bearer token from localStorage is attached automatically.
 * Browsers can't use EventSource for POST (GET-only), so we use fetch() with
 * ReadableStream and parse SSE wire format manually.
 *
 * opts.kbId — if set, the backend runs in KB-bound mode (search_kb).
 * If null/undefined, the agent runs in unbound general-chat mode.
 *
 * Returns a cancel function that aborts the in-flight request.
 */
export function connectChat(
  messages: ChatMessage[],
  onEvent: (e: ChatEvent) => void,
  opts?: { conversationId?: string | null; kbId?: string | null; model?: string | null; modelProfileId?: string | null }
): () => void {
  const controller = new AbortController();

  (async () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const body: Record<string, unknown> = opts?.conversationId
      ? { conversation_id: opts.conversationId }
      : { messages };
    if (opts?.kbId) body.kb_id = opts.kbId;
    if (opts?.model) body.model = opts.model;
    if (opts?.modelProfileId) body.model_profile_id = opts.modelProfileId;

    let resp: Response;
    try {
      resp = await fetch("/api/chat", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== "AbortError") {
        const raw = (err as Error)?.message ?? "network failed";
        const lower = raw.toLowerCase();
        const message =
          lower.includes("network error") ||
          lower.includes("failed to fetch") ||
          lower.includes("load failed")
            ? "连接中断：后端可能正在热重载或网络超时，请重试。"
            : raw;
        onEvent({ event: "error", message });
      }
      return;
    }

    if (!resp.ok || !resp.body) {
      if (resp.status === 401) {
        handleSessionExpired();
        return;
      }
      // Surface backend's structured 422 (BYOK gate) so the page can act on
      // `code` (llm_not_configured / embedding_not_configured) and redirect
      // the user to /settings.
      let message = `HTTP ${resp.status}`;
      let code: string | undefined;
      let settings_url: string | undefined;
      let retry_after_seconds: number | undefined;
      try {
        const text = await resp.text();
        try {
          const j = JSON.parse(text);
          const detail = j?.detail;
          if (detail && typeof detail === "object") {
            message = detail.message || text;
            code = detail.code;
            settings_url = detail.settings_url;
            retry_after_seconds =
              typeof detail.retry_after_seconds === "number"
                ? detail.retry_after_seconds
                : undefined;
          } else if (typeof detail === "string") {
            message = detail;
          } else {
            message = text || message;
          }
        } catch {
          message = text || message;
        }
      } catch {
        /* noop */
      }
      if (code === "rate_limit_exceeded" || message === "rate_limit_exceeded") {
        message = formatRateLimitMessage(retry_after_seconds);
      }
      onEvent({ event: "error", message, code, settings_url, retry_after_seconds });
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // sse-starlette emits CRLF line endings; normalize to LF so the rest
        // of the parser can split on plain "\n\n" frame boundaries.
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

        // SSE frames are separated by blank lines (\n\n after normalization).
        let sepIdx: number;
        while ((sepIdx = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sepIdx);
          buffer = buffer.slice(sepIdx + 2);

          // Each frame may have multiple lines; we only care about "data:".
          // (sse-starlette emits "event: message\ndata: {json}\n\n".)
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try {
              const evt = JSON.parse(payload) as ChatEvent;
              onEvent(evt);
              if (evt.event === "done" || evt.event === "error") {
                controller.abort();
                return;
              }
            } catch (err) {
              console.error("parse SSE failed", err, payload);
            }
          }
        }
      }
      // Upstream closed without a terminal SSE event (proxy drop /
      // uvicorn --reload). Surface a recoverable error instead of hanging busy.
      if (!controller.signal.aborted) {
        onEvent({
          event: "error",
          message: "连接中断：流式响应未正常结束。若正在改后端代码，请重试一次。",
        });
      }
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== "AbortError") {
        onEvent({
          event: "error",
          message: friendlyStreamError(err),
        });
      }
    }
  })();

  return () => controller.abort();
}

function friendlyStreamError(err: unknown): string {
  const raw = (err as Error)?.message ?? "stream interrupted";
  const lower = raw.toLowerCase();
  if (
    lower.includes("network error") ||
    lower.includes("failed to fetch") ||
    lower.includes("load failed") ||
    lower.includes("connection")
  ) {
    return "连接中断：后端可能正在热重载或网络超时，请重试。";
  }
  return raw;
}

function formatRateLimitMessage(retryAfterSeconds?: number): string {
  if (typeof retryAfterSeconds === "number" && retryAfterSeconds > 0) {
    const minutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));
    return `发送过于频繁，请约 ${minutes} 分钟后再试。本次提问尚未处理。`;
  }
  return "发送过于频繁，请稍后再试。本次提问尚未处理。";
}
