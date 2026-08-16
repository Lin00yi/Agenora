import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/components/ExportActions", () => ({
  default: () => null,
}));
vi.mock("../ExportActions", () => ({
  default: () => null,
}));

import { ChatMessage } from "@/components/chat/ChatMessages";

describe("ChatMessage process trace placement", () => {
  it("shows an animated loading indicator before the first streamed token", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-streaming",
          role: "assistant",
          content: "",
          created_at: Date.now(),
          tools: [],
          streaming: true,
        }}
      />
    );

    expect(screen.getByText("正在思考")).toBeTruthy();
    expect(screen.getByText("正在思考").parentElement?.querySelector("svg")?.getAttribute("class")).toContain(
      "animate-spin"
    );
  });

  it("removes the duplicate generation status after streamed text begins", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-streaming-text",
          role: "assistant",
          content: "正在流式输出的正文",
          created_at: Date.now(),
          tools: [],
          streaming: true,
        }}
      />
    );

    expect(screen.getByText("正在流式输出的正文")).toBeTruthy();
    expect(screen.queryByText("正在生成回答")).toBeNull();
  });

  it("keeps the final answer visible while the pre-tool note lives inside the expanded trace", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-1",
          role: "assistant",
          content: "",
          created_at: Date.now(),
          tools: [{ id: "tool-1", name: "search_kb", status: "ok", t0: 1_000, latency_ms: 2_000 }],
          parts: [
            { type: "text", text: "我会先检索已有资料。" },
            {
              type: "tools",
              tools: [
                {
                  id: "tool-1",
                  name: "search_kb",
                  status: "ok",
                  t0: 1_000,
                  latency_ms: 2_000,
                  input: { query: "部署说明" },
                },
              ],
            },
            { type: "text", text: "这是整理后的正式回答。" },
          ],
        }}
      />
    );

    expect(screen.getByText("这是整理后的正式回答。")).toBeTruthy();
    expect(screen.queryByText("我会先检索已有资料。")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /已处理 2 秒/ }));

    expect(screen.getByText("我会先检索已有资料。")).toBeTruthy();
    expect(screen.getByText("部署说明")).toBeTruthy();
  });

  it("shows the safe prepared-context trace before a response starts streaming", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-context",
          role: "assistant",
          content: "",
          created_at: Date.now(),
          tools: [],
          streaming: true,
          parts: [
            {
              type: "context",
              trace: {
                runtime: { mode: "general", safety: "standard" },
                recent_message_count: 1,
                prompt: {
                  model: "test-model",
                  context_window: 16_000,
                  tokens: {
                    system: 800,
                    tools: 300,
                    rag: 1_200,
                    history: 400,
                    output: 2_048,
                    safety: 2_000,
                    total_input: 2_700,
                  },
                  truncation: { rag: true, history: false },
                },
              },
            },
          ],
        }}
      />
    );

    const contextButton = screen.getByRole("button", { name: /上下文已准备/ });
    expect(contextButton.textContent).toContain("通用模式");
    expect(screen.getByText("正在思考")).toBeTruthy();

    fireEvent.click(contextButton);
    expect(screen.getByText("运行规则与安全边界已加载。", { exact: true })).toBeTruthy();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "P" &&
          element.textContent?.includes("本轮请求 · 输入 2.7k / 窗口 16.0k") === true
      )
    ).toBeTruthy();
    expect(screen.getByText(/已按预算裁剪检索资料/)).toBeTruthy();
  });
});
