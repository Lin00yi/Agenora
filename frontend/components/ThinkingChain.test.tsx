import React from "react";
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ThinkingChain from "@/components/ThinkingChain";

describe("ThinkingChain", () => {
  it("renders grouped parallel tool calls with per-query durations", () => {
    render(
      <ThinkingChain
        events={[
          {
            name: "search_kb",
            status: "ok",
            latency_ms: 1260,
            input: { query: "Agenora data security", limit: 5 },
          },
          {
            name: "search_kb",
            status: "ok",
            latency_ms: 387,
            input: { query: "Agenora privacy", limit: 5 },
          },
        ]}
      />
    );

    expect(screen.getByText(/\u5df2\u5e76\u884c\u68c0\u7d22 KB/)).toBeTruthy();
    expect(screen.getAllByText("1.3s").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2 \u6761\u67e5\u8be2 \u00b7 \u5168\u90e8\u5b8c\u6210/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("Agenora data security")).toBeTruthy();
    expect(screen.getByText("Agenora privacy")).toBeTruthy();
    expect(screen.getByText("387ms")).toBeTruthy();
  });
});
