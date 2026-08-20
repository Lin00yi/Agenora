import { describe, expect, it } from "vitest";
import { parseChatKbSelectionMode } from "./chat-kb-policy";

describe("parseChatKbSelectionMode", () => {
  it("hides the picker by default and for unsupported values", () => {
    expect(parseChatKbSelectionMode(undefined)).toBe("hidden");
    expect(parseChatKbSelectionMode("")).toBe("hidden");
    expect(parseChatKbSelectionMode("always")).toBe("hidden");
  });

  it("enables selection only when explicitly configured", () => {
    expect(parseChatKbSelectionMode("selectable")).toBe("selectable");
    expect(parseChatKbSelectionMode(" SELECTABLE ")).toBe("selectable");
  });
});
