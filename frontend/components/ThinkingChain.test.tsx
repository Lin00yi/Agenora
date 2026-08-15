import React from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ThinkingChain from "@/components/ThinkingChain";

describe("ThinkingChain", () => {
  it("renders a compact completed summary and expands to a chronological trace", () => {
    const { container } = render(
      <ThinkingChain
        events={[
          {
            name: "search_kb",
            status: "ok",
            t0: 1_000,
            latency_ms: 1260,
            input: { query: "Agenora data security", limit: 5 },
          },
          {
            name: "search_kb",
            status: "ok",
            t0: 1_000,
            latency_ms: 387,
            input: { query: "Agenora privacy", limit: 5 },
          },
        ]}
      />
    );

    expect(screen.getByText("已处理 1 秒")).toBeTruthy();
    expect(screen.queryByText("Agenora data security")).toBeNull();
    expect(container.querySelector("section > .border-t")).toBeTruthy();

    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("Agenora data security")).toBeTruthy();
    expect(screen.getByText("Agenora privacy")).toBeTruthy();
    expect(screen.getAllByText("1 秒").length).toBeGreaterThanOrEqual(2);
  });

  it("opens while running and includes the public lead-in below the summary", () => {
    render(
      <ThinkingChain
        intro="我会先查阅现有资料。"
        events={[{ name: "search_kb", status: "running", input: { query: "部署说明" } }]}
      />
    );

    expect(screen.getAllByText("正在检索知识库")).toHaveLength(2);
    expect(screen.getByText("我会先查阅现有资料。")).toBeTruthy();
    expect(screen.getByText("部署说明")).toBeTruthy();
    expect(screen.getByRole("button").querySelector("svg")?.getAttribute("class")).toContain(
      "animate-spin"
    );
  });
});
