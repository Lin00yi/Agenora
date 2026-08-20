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
});
