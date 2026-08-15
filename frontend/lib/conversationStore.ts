"use client";

import type { ToolEvent } from "@/components/ThinkingChain";
import type { Citation, MemoryTrace } from "@/lib/sseClient";

/**
 * Conversation type definitions + small pure helpers.
 *
 * v2-M3: storage moved server-side (see lib/conversations-api.ts). This file
 * keeps only the shape types and stateless utilities the UI still needs for
 * ephemeral streaming state (a temporary assistant message in React state
 * before SSE done fires and we persist).
 */

/** Sealed timeline segments for one assistant turn (Phase 3 interleaved stream). */
export type AssistantPart =
  | { type: "text"; text: string }
  | { type: "tools"; tools: ToolEvent[] };

export type Message =
  | {
      id: string;
      role: "user";
      content: string;
      created_at: number;
    }
  | {
      id: string;
      role: "assistant";
      /** Joined text for persistence / export; live open segment while streaming. */
      content: string;
      tools: ToolEvent[]; // flat tool timeline (persist + legacy)
      /** Interleaved text/tool segments for Cursor-like rendering. */
      parts?: AssistantPart[];
      memory_trace?: MemoryTrace | null;
      citations?: Citation[] | null;
      streaming?: boolean;
      cost_usd?: number;
      error?: string;
      created_at: number;
    };

export type Conversation = {
  id: string;
  title: string;
  messages: Message[];
  /** KB this conversation is bound to. null = unbound mode (multi-tool agent). */
  kb_id?: string | null;
  /** v3-M6: per-conversation LLM model override. null = use user default. */
  llm_model?: string | null;
  message_count?: number;
  created_at: number;
  updated_at: number;
  finalized_at?: number | null;
};

export function deriveTitle(msg: string): string {
  const cleaned = msg.trim().replace(/\s+/g, " ");
  return cleaned.length > 24 ? cleaned.slice(0, 24) + "…" : cleaned;
}

export function genMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

/** Flatten parts + live content into persistable markdown. */
export function joinAssistantText(
  parts: AssistantPart[] | undefined,
  liveContent: string
): string {
  const chunks: string[] = [];
  for (const part of parts ?? []) {
    if (part.type === "text" && part.text.trim()) chunks.push(part.text.trimEnd());
  }
  if (liveContent.trim()) chunks.push(liveContent.trimEnd());
  return chunks.join("\n\n");
}

/** Flatten tool events from parts (fallback to legacy tools array). */
export function flattenAssistantTools(
  parts: AssistantPart[] | undefined,
  legacyTools: ToolEvent[]
): ToolEvent[] {
  const fromParts: ToolEvent[] = [];
  for (const part of parts ?? []) {
    if (part.type === "tools") fromParts.push(...part.tools);
  }
  return fromParts.length > 0 ? fromParts : legacyTools;
}

/**
 * Close the currently streaming text segment before persisting a turn.
 * Returns undefined for ordinary text-only replies, which keeps their compact
 * legacy representation. Tool-interleaved replies retain their exact order.
 */
export function finalizeAssistantParts(
  parts: AssistantPart[],
  liveContent: string
): AssistantPart[] | undefined {
  if (parts.length === 0) return undefined;
  const finalParts = parts.map((part) =>
    part.type === "text" ? { ...part } : { type: "tools" as const, tools: [...part.tools] }
  );
  if (liveContent.trim()) {
    finalParts.push({ type: "text", text: liveContent });
  }
  return finalParts;
}

/** Parse persisted timeline data defensively so old/corrupt rows stay readable. */
export function parseAssistantParts(value: unknown): AssistantPart[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const parts: AssistantPart[] = [];
  for (const part of value) {
    if (!part || typeof part !== "object") continue;
    const candidate = part as { type?: unknown; text?: unknown; tools?: unknown };
    if (candidate.type === "text" && typeof candidate.text === "string") {
      parts.push({ type: "text", text: candidate.text });
    } else if (candidate.type === "tools" && Array.isArray(candidate.tools)) {
      parts.push({ type: "tools", tools: candidate.tools as ToolEvent[] });
    }
  }
  return parts.length > 0 ? parts : undefined;
}
