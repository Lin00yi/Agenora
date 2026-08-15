"use client";

import { authFetch } from "./auth";
import type { ToolEvent } from "@/components/ThinkingChain";
import type { AssistantPart } from "@/lib/conversationStore";
import type { MemoryTrace } from "@/lib/sseClient";

/**
 * Conversations API client (v2-M3).
 *
 * Replaces the v1 localStorage-only store. All endpoints proxied through
 * /api/conversations/* (Next route hops to backend with Bearer attached).
 *
 * Frontend orchestration (no server-side chat persistence):
 *   1. user types        → appendMessage(role: "user")
 *   2. SSE chat fires    → existing sseClient.connectChat
 *   3. SSE done/error    → appendMessage(role: "assistant", tools, cost_usd, error?)
 *
 * Keep types in sync with backend/src/conversations/models.py.
 */

export type ConversationSummary = {
  id: string;
  title: string;
  kb_id: string | null;
  /** v3-M6: per-conversation LLM model override. null = use user default. */
  llm_model: string | null;
  /** Stable model-profile selection. Null keeps the automatic route. */
  llm_profile_id: string | null;
  message_count: number;
  created_at: string | null;
  updated_at: string | null;
  finalized_at: string | null;
  context_status?: ConversationContextStatus | null;
};

export type ConversationContextStatus = {
  state: "normal" | "approaching" | "ready" | "critical" | "compressed";
  label: string;
  description: string;
  current_tokens: number;
  /** Uncompressed message history size; present when backend reports effective usage. */
  raw_history_tokens?: number;
  available_tokens: number;
  context_window: number;
  ratio: number;
  percent: number;
  prepare_threshold_percent: number;
  summary_threshold_percent: number;
  force_threshold_percent: number;
  retained_recent_turns: number;
  summary: {
    id: string;
    covered_message_count: number;
    token_count: number;
    source_model?: string | null;
    source_context_window?: number | null;
    updated_at: string | null;
  } | null;
};

export type CitationPayload = {
  channel: "kb" | "web";
  title: string;
  source: string;
  score?: number | null;
  url?: string | null;
  snippet?: string | null;
  kb_id?: string | null;
  doc_id?: string | null;
};

export type MessagePayload = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolEvent[] | null;
  /** Persisted text/tool order for streamed assistant replies. */
  parts?: AssistantPart[] | null;
  memory_trace?: MemoryTrace | null;
  citations?: CitationPayload[] | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string | null;
};

export type ConversationDetail = ConversationSummary & {
  messages: MessagePayload[];
};

export type ConversationListPage = {
  items: ConversationSummary[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export type UserMemory = {
  id: string;
  user_id: string;
  scope: "personal" | "kb" | string;
  scope_id: string | null;
  type: "explicit" | "preference" | "constraint" | string;
  key: string | null;
  value: string | null;
  content: string;
  source_message_ids: string[];
  source: "explicit" | "auto_rule" | "user_edited" | string;
  confidence: number;
  importance: number;
  status: "active" | "superseded" | "deleted" | string;
  expires_at: string | null;
  supersedes_memory_id: string | null;
  has_embedding: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type FinalizeConversationResult = {
  already_finalized: boolean;
  conversation: ConversationSummary;
  memory: {
    messages_scanned: number;
    rule_candidates: number;
    llm_candidates: number;
    stored: number;
  };
};

/** Structured error mirror of KbApiError. */
export class ConversationApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    if (detail && typeof detail === "object") {
      const d = detail as { code?: string };
      this.code = d.code;
    }
  }
}

async function unwrap<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail: unknown = null;
    let message = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      detail = j.detail ?? j;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        const d = detail as { message?: string };
        message = typeof d.message === "string" ? d.message : JSON.stringify(detail);
      }
    } catch {
      /* keep default */
    }
    throw new ConversationApiError(r.status, detail, message);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------
export async function listConversations(): Promise<ConversationSummary[]>;
export async function listConversations(opts: {
  page: number;
  pageSize?: number;
  q?: string;
}): Promise<ConversationListPage>;
export async function listConversations(opts?: {
  page: number;
  pageSize?: number;
  q?: string;
}): Promise<ConversationSummary[] | ConversationListPage> {
  if (!opts) return unwrap(await authFetch("/api/conversations"));
  const q = new URLSearchParams({
    page: String(opts.page),
    page_size: String(opts.pageSize ?? 30),
  });
  const query = opts.q?.trim();
  if (query) q.set("q", query);
  return unwrap(await authFetch(`/api/conversations?${q}`));
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return unwrap(await authFetch(`/api/conversations/${id}`));
}

export async function getConversationContextStatus(
  id: string
): Promise<ConversationContextStatus> {
  return unwrap(await authFetch(`/api/conversations/${id}/context-status`));
}

export async function createConversation(
  opts: { kb_id?: string | null; title?: string } = {}
): Promise<ConversationDetail> {
  return unwrap(
    await authFetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kb_id: opts.kb_id ?? null, title: opts.title }),
    })
  );
}

export async function patchConversation(
  id: string,
  patch: { title?: string; kb_id?: string | null; llm_model?: string | null; llm_profile_id?: string | null }
): Promise<ConversationSummary> {
  return unwrap(
    await authFetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export async function deleteConversation(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/conversations/${id}`, { method: "DELETE" }));
}

export async function finalizeConversation(id: string): Promise<FinalizeConversationResult> {
  return unwrap(await authFetch(`/api/conversations/${id}/finalize`, { method: "POST" }));
}

// ---------------------------------------------------------------------------
// Long-term memory (captured silently in the backend; these helpers support
// future settings/audit UI without putting a confirmation step in chat).
// ---------------------------------------------------------------------------
export async function listMemories(opts: { status?: string } = {}): Promise<UserMemory[]> {
  const q = new URLSearchParams();
  if (opts.status) q.set("status", opts.status);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return unwrap(await authFetch(`/api/conversations/memories${suffix}`));
}

export async function patchMemory(
  id: string,
  patch: {
    content?: string;
    value?: string;
    importance?: number;
    status?: "active" | "deleted";
    /** ISO timestamp, or null to clear expiry (long-lived). */
    expires_at?: string | null;
  }
): Promise<UserMemory> {
  return unwrap(
    await authFetch(`/api/conversations/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export async function deleteMemory(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/conversations/memories/${id}`, { method: "DELETE" }));
}

/** Trigger a browser download of long-term memories as JSON. */
export async function exportMemories(opts: { status?: string } = {}): Promise<void> {
  const q = new URLSearchParams();
  if (opts.status) q.set("status", opts.status);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  const r = await authFetch(`/api/conversations/memories/export${suffix}`);
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
    throw new ConversationApiError(r.status, detail, `memory export failed: ${r.status}`);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "agenora-memories.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// v3-M5: bulk delete + export
// ---------------------------------------------------------------------------
export async function deleteAllConversations(): Promise<void> {
  await unwrap(await authFetch("/api/conversations", { method: "DELETE" }));
}

/** Trigger a browser download of all conversations as JSON. */
export async function exportConversations(): Promise<void> {
  const r = await authFetch("/api/conversations/export");
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
    throw new ConversationApiError(r.status, detail, `export failed: ${r.status}`);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "agenora-export.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------
export async function appendUserMessage(
  convId: string,
  content: string
): Promise<MessagePayload> {
  return unwrap(
    await authFetch(`/api/conversations/${convId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: "user", content }),
    })
  );
}

export async function appendAssistantMessage(
  convId: string,
  payload: {
    content: string;
    tools?: ToolEvent[];
    parts?: AssistantPart[];
    memory_trace?: MemoryTrace | null;
    citations?: CitationPayload[] | null;
    cost_usd?: number;
    error?: string;
  }
): Promise<MessagePayload> {
  return unwrap(
    await authFetch(`/api/conversations/${convId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        role: "assistant",
        content: payload.content,
        tools: payload.tools && payload.tools.length > 0 ? payload.tools : undefined,
        parts: payload.parts && payload.parts.length > 0 ? payload.parts : undefined,
        memory_trace: payload.memory_trace ?? undefined,
        citations:
          payload.citations && payload.citations.length > 0
            ? payload.citations
            : undefined,
        cost_usd: payload.cost_usd,
        error: payload.error,
      }),
    })
  );
}

// ---------------------------------------------------------------------------
// Bulk import (v1 localStorage → server, one-shot per browser)
// ---------------------------------------------------------------------------
type LocalMessage =
  | { role: "user"; content: string; created_at?: number }
  | {
      role: "assistant";
      content: string;
      tools?: ToolEvent[];
      cost_usd?: number;
      error?: string;
      created_at?: number;
    };

type LocalConversation = {
  id?: string;
  title?: string;
  kb_id?: string | null;
  created_at?: number;
  updated_at?: number;
  messages: LocalMessage[];
};

/**
 * Push any leftover localStorage conversations to the server, exactly once.
 * Idempotent via `agenora:migrated:{userId}` flag.
 *
 * Returns the imported count (0 if nothing to migrate or already migrated).
 */
export async function migrateFromLocalStorage(userId: string): Promise<number> {
  if (typeof window === "undefined") return 0;
  const ls = window.localStorage;
  const migratedFlag = `agenora:migrated:${userId}`;
  if (ls.getItem(migratedFlag) === "true" || ls.getItem(`anykb:migrated:${userId}`) === "true") {
    ls.setItem(migratedFlag, "true");
    return 0;
  }

  const oldConvKey =
    ls.getItem(`agenora:conversations:${userId}`) != null
      ? `agenora:conversations:${userId}`
      : `anykb:conversations:${userId}`;
  const oldCurrKey =
    oldConvKey.startsWith("agenora:")
      ? `agenora:current_conversation_id:${userId}`
      : `anykb:current_conversation_id:${userId}`;
  const raw = ls.getItem(oldConvKey);
  if (!raw) {
    ls.setItem(migratedFlag, "true");
    return 0;
  }

  let list: LocalConversation[] = [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) list = parsed as LocalConversation[];
  } catch {
    // Garbage data — clear it and move on, no point retrying.
    ls.removeItem(oldConvKey);
    ls.removeItem(oldCurrKey);
    ls.setItem(migratedFlag, "true");
    return 0;
  }

  if (list.length === 0) {
    ls.removeItem(oldConvKey);
    ls.removeItem(oldCurrKey);
    ls.setItem(migratedFlag, "true");
    return 0;
  }

  const body = {
    conversations: list.map((c) => ({
      title: c.title ?? "新对话",
      kb_id: c.kb_id ?? null,
      created_at: c.created_at,
      updated_at: c.updated_at,
      messages: (c.messages ?? []).map((m) => {
        if (m.role === "user") {
          return { role: "user", content: m.content, created_at: m.created_at };
        }
        return {
          role: "assistant",
          content: m.content,
          tools: m.tools,
          cost_usd: m.cost_usd,
          error: m.error,
          created_at: m.created_at,
        };
      }),
    })),
  };

  const result = await unwrap<{ imported: number }>(
    await authFetch("/api/conversations/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );

  // Only clean up on success — leaves data intact for retry on failure.
  ls.removeItem(oldConvKey);
  ls.removeItem(oldCurrKey);
  ls.setItem(migratedFlag, "true");
  return result.imported ?? 0;
}
