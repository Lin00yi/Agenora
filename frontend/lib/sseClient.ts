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
    | "tool_start"
    | "tool_end"
    | "tool_blocked"
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
  cost_usd?: number;
  memory_trace?: MemoryTrace | null;
  citations?: Citation[] | null;
  message?: string;
  kb_id?: string | null;
  /** v2-M2 BYOK gate: `llm_not_configured` | `embedding_not_configured` */
  code?: string;
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
 * opts.kbId — if set, the backend runs in KB-bound mode (search_kb only).
 * If null/undefined, the agent runs in unbound mode (system travel demo
 * fallback or multi-tool when no kb_id is passed).
 *
 * Returns a cancel function that aborts the in-flight request.
 */
export function connectChat(
  messages: ChatMessage[],
  onEvent: (e: ChatEvent) => void,
  opts?: { conversationId?: string | null; kbId?: string | null; model?: string | null }
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
        onEvent({ event: "error", message: (err as Error)?.message ?? "network failed" });
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
      try {
        const text = await resp.text();
        try {
          const j = JSON.parse(text);
          const detail = j?.detail;
          if (detail && typeof detail === "object") {
            message = detail.message || text;
            code = detail.code;
            settings_url = detail.settings_url;
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
      onEvent({ event: "error", message, code, settings_url });
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
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== "AbortError") {
        onEvent({ event: "error", message: (err as Error)?.message ?? "stream interrupted" });
      }
    }
  })();

  return () => controller.abort();
}
