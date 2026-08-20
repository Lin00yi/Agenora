import { describe, expect, it } from "vitest";
import type { ToolEvent } from "@/components/ThinkingChain";
import type { Message } from "@/lib/conversationStore";
import { pendingHumanInput } from "./useChatSend";

const confirmationEvent: ToolEvent = {
  id: "human-input-1",
  name: "human_input_required",
  status: "ok",
  t0: 0,
  input: {
    slot: "refund_confirmation",
    approval_id: "RFD-1",
    confirmation_phrase: "确认退款 RFD-1",
    prompt: "请确认退款。",
  },
};

const confirmationRequest: Message = {
  id: "assistant-confirmation",
  role: "assistant",
  content: "",
  tools: [confirmationEvent],
  created_at: 1,
};

describe("pendingHumanInput", () => {
  it("restores an awaiting confirmation after a reload", () => {
    expect(pendingHumanInput([confirmationRequest])).toMatchObject({
      phase: "awaiting",
      slot: "refund_confirmation",
      approvalId: "RFD-1",
    });
  });

  it("keeps the confirmation surface disabled after it was submitted", () => {
    const submitted: Message = {
      id: "user-confirmation",
      role: "user",
      content: "确认退款 RFD-1",
      created_at: 2,
    };
    expect(pendingHumanInput([confirmationRequest, submitted])).toMatchObject({
      phase: "processing",
      confirmationPhrase: "确认退款 RFD-1",
    });
  });

  it("clears the recovery surface once a later assistant result is durable", () => {
    const completed: Message = {
      id: "assistant-completed",
      role: "assistant",
      content: "退款已完成。",
      tools: [],
      created_at: 3,
    };
    expect(pendingHumanInput([confirmationRequest, completed])).toBeNull();
  });
});
