import { describe, expect, it } from "vitest";

import { normalizeMessages, serverMsgToLocal } from "./chatPageHelpers";

describe("serverMsgToLocal", () => {
  it("keeps a persisted empty streaming draft renderable after refresh", () => {
    const draft = serverMsgToLocal({
      id: "assistant-draft",
      role: "assistant",
      content: "",
      tools: [],
      streaming: true,
      cost_usd: null,
      error: null,
      created_at: "2026-08-20T10:00:00Z",
    });

    expect(draft).toMatchObject({ role: "assistant", streaming: true });
    expect(normalizeMessages([draft])).toEqual([draft]);
  });
});
