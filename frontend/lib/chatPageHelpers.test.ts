import { describe, expect, it } from "vitest";
import {
  conversationHref,
  conversationIdFromPath,
  getContextWindowForModel,
  uniqueStrings,
} from "@/lib/chatPageHelpers";

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
});
