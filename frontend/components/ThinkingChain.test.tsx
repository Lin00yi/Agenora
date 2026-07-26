import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ThinkingChain from "@/components/ThinkingChain";

describe("ThinkingChain", () => {
  it("renders steps count and readable tool input", () => {
    render(
      <ThinkingChain
        events={[
          {
            name: "search_kb",
            status: "ok",
            latency_ms: 200,
            input: { query: "AnyKB data security", limit: 5 },
          },
          { name: "search_restaurant_kb", status: "running" },
        ]}
      />
    );

    expect(screen.getByText(/思考中 · 1\/2 步/)).toBeTruthy();
    expect(screen.getByText("查询")).toBeTruthy();
    expect(screen.getByText("AnyKB data security")).toBeTruthy();
    expect(screen.getByText("TopK")).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();
  });
});
