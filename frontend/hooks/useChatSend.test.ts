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

  it("restores server-authoritative refundable order options for step one", () => {
    const orderSelection: Message = {
      ...confirmationRequest,
      id: "assistant-select-order",
      tools: [{
        ...confirmationEvent,
        input: {
          slot: "order_id",
          prompt: "请选择要退款的订单。",
          order_options: [{
            order_id: "ORD-1001",
            product_name: "AeroPods 降噪耳机",
            product_url: "https://demo.agenora.local/products/aeropods-pro",
            status_label: "已支付，待发货",
            refundable_minor: 11700,
            currency: "CNY",
            refund_to: "微信支付",
          }],
        },
      }],
    };

    expect(pendingHumanInput([orderSelection])).toMatchObject({
      slot: "order_id",
      orderOptions: [{
        orderId: "ORD-1001",
        productName: "AeroPods 降噪耳机",
        refundableMinor: 11700,
      }],
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
