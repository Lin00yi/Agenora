import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMessage } from "./ChatMessages";

describe("ChatMessage", () => {
  it("renders the persisted interrupt prompt when a legacy assistant row has no content", () => {
    render(
      <ChatMessage
        message={{
          id: "interrupt-1",
          role: "assistant",
          content: "",
          created_at: Date.now(),
          tools: [
            {
              id: "human-1",
              name: "human_input_required",
              status: "ok",
              input: { prompt: "请选择要退款的订单。" },
            },
          ],
        }}
      />
    );

    expect(screen.getByText("请选择要退款的订单。")).toBeTruthy();
  });

  it("keeps restored context above the processing trace", () => {
    const { container } = render(
      <ChatMessage
        message={{
          id: "restored-1",
          role: "assistant",
          content: "请填写退款原因。",
          created_at: Date.now(),
          tools: [{ id: "tool-1", name: "get_order", status: "ok" }],
          memory_trace: {
            runtime: { mode: "general", agent_runtime: "supervisor" },
            recent_message_count: 5,
          },
        }}
      />
    );

    const context = screen.getByText(/上下文已准备/);
    const processing = screen.getByText(/已处理/);
    expect(context.compareDocumentPosition(processing) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(container.textContent).toContain("请填写退款原因。");
  });
});
