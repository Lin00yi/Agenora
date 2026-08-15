import { describe, expect, it } from "vitest";

import {
  finalizeAssistantParts,
  joinAssistantText,
  parseAssistantParts,
} from "@/lib/conversationStore";

describe("assistant timeline persistence", () => {
  it("seals the final text after an interleaved tool segment", () => {
    const parts = finalizeAssistantParts(
      [
        { type: "text", text: "我先查一下。" },
        { type: "tools", tools: [{ id: "t1", name: "web_search", status: "ok" }] },
      ],
      "这是查询后的回答。"
    );

    expect(parts).toEqual([
      { type: "text", text: "我先查一下。" },
      { type: "tools", tools: [{ id: "t1", name: "web_search", status: "ok" }] },
      { type: "text", text: "这是查询后的回答。" },
    ]);
    expect(joinAssistantText(parts, "")).toBe("我先查一下。\n\n这是查询后的回答。");
  });

  it("keeps legacy text-only replies compact and ignores malformed persisted parts", () => {
    expect(finalizeAssistantParts([], "直接回答")).toBeUndefined();
    expect(parseAssistantParts([{ type: "unknown" }, { type: "text", text: "可恢复" }])).toEqual([
      { type: "text", text: "可恢复" },
    ]);
  });
});
