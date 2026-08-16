import { describe, expect, it } from "vitest";
import {
  conversationHref,
  conversationIdFromPath,
  getContextWindowForModel,
  normalizeMessages,
  parseServerTimestamp,
  serverMsgToLocal,
  uniqueStrings,
} from "@/lib/chatPageHelpers";
import { joinAssistantText } from "@/lib/conversationStore";

describe("chatPageHelpers", () => {
  it("resolves known model context windows and falls back safely", () => {
    expect(getContextWindowForModel("gpt-4o")).toBe(128_000);
    expect(getContextWindowForModel("unknown-model")).toBe(16_000);
    expect(getContextWindowForModel(null, ["claude-sonnet-4-6"])).toBe(200_000);
  });

  it("builds and parses conversation paths", () => {
    expect(conversationHref("abc/def")).toBe("/c/abc%2Fdef");
    expect(conversationIdFromPath("/c/abc%2Fdef")).toBe("abc/def");
    expect(conversationIdFromPath("/kbs/1")).toBeNull();
  });

  it("dedupes strings while dropping empties", () => {
    expect(uniqueStrings(["a", null, "a", "", "b", undefined])).toEqual(["a", "b"]);
  });

  it("treats legacy timezone-less API timestamps as UTC", () => {
    const expected = Date.UTC(2026, 7, 14, 7, 22, 0);
    expect(parseServerTimestamp("2026-08-14T07:22:00")).toBe(expected);
    expect(parseServerTimestamp("2026-08-14T07:22:00+00:00")).toBe(expected);
  });

  it("rehydrates a persisted tool timeline without duplicating its text", () => {
    const message = serverMsgToLocal({
      id: "assistant-1",
      role: "assistant",
      content: "先检索。\n\n再回答。",
      tools: [{ id: "tool-1", name: "search_kb", status: "ok" }],
      parts: [
        { type: "text", text: "先检索。" },
        { type: "tools", tools: [{ id: "tool-1", name: "search_kb", status: "ok" }] },
        { type: "text", text: "再回答。" },
      ],
      cost_usd: null,
      error: null,
      created_at: "2026-08-14T07:22:00+00:00",
    });

    if (message.role !== "assistant") throw new Error("expected assistant message");
    expect(message.content).toBe("");
    expect(joinAssistantText(message.parts, message.content)).toBe("先检索。\n\n再回答。");
  });

  it("keeps persisted context and text timelines after a conversation refresh", () => {
    const message = serverMsgToLocal({
      id: "assistant-with-context",
      role: "assistant",
      content: "这是持久化的完整回答。",
      tools: [],
      parts: [
        {
          type: "context",
          trace: { runtime: { mode: "general", safety: "standard" } },
        },
        { type: "text", text: "这是持久化的完整回答。" },
      ],
      cost_usd: null,
      error: null,
      created_at: "2026-08-16T06:23:01+00:00",
    });

    expect(normalizeMessages([message])).toEqual([message]);
  });
});
