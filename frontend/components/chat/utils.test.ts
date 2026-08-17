import { describe, expect, it } from "vitest";
import { formatMessageTime } from "./utils";

describe("formatMessageTime", () => {
  const now = new Date(2026, 7, 14, 15, 25, 45).getTime();

  it("shows only the local time for messages from today", () => {
    const messageTime = new Date(2026, 7, 14, 9, 3, 5).getTime();
    expect(formatMessageTime(messageTime, now)).toBe("09:03");
  });

  it("shows a full local timestamp for messages from another day", () => {
    const messageTime = new Date(2026, 7, 13, 9, 3, 5).getTime();
    expect(formatMessageTime(messageTime, now)).toBe("2026-08-13\u200209:03:05");
  });
});
