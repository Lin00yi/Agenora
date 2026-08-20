import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { HumanInputPanel, type HumanInputRequest } from "./HumanInputPanel";

const orderRequest: HumanInputRequest = {
  slot: "order_id",
  prompt: "请选择要退款的订单。",
  orderOptions: [
    {
      orderId: "ORD-1001",
      productName: "AeroPods 降噪耳机",
      statusLabel: "已支付，待发货",
      refundableMinor: 11700,
      currency: "CNY",
    },
  ],
};

function StatefulPanel({ request, onSubmit }: { request: HumanInputRequest; onSubmit: (value?: string) => void }) {
  const [value, setValue] = useState("");
  return <HumanInputPanel request={request} value={value} busy={false} onChange={setValue} onSubmit={onSubmit} />;
}

describe("HumanInputPanel", () => {
  it("shows only service-provided refundable orders instead of an order-id text input", () => {
    const onSubmit = vi.fn();
    render(<StatefulPanel request={orderRequest} onSubmit={onSubmit} />);

    expect(screen.getByText("AeroPods 降噪耳机")).toBeTruthy();
    expect(screen.getByText("¥117.00")).toBeTruthy();
    expect(screen.queryByLabelText("订单")).toBeNull();
    expect((screen.getByRole("button", { name: "继续填写原因" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("radio", { name: /AeroPods 降噪耳机/ }));
    fireEvent.click(screen.getByRole("button", { name: "继续填写原因" }));
    expect(onSubmit).toHaveBeenCalledWith("ORD-1001");
  });

  it("requires a preset reason or details and submits the composed reason", () => {
    const onSubmit = vi.fn();
    render(<StatefulPanel request={{ slot: "refund_reason", prompt: "请填写退款原因。" }} onSubmit={onSubmit} />);

    expect((screen.getByRole("button", { name: "生成退款确认单" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "商品质量问题" }));
    fireEvent.change(screen.getByLabelText(/补充说明/), { target: { value: "外壳有划痕" } });
    fireEvent.click(screen.getByRole("button", { name: "生成退款确认单" }));
    expect(onSubmit).toHaveBeenCalledWith("商品质量问题：外壳有划痕");
    expect((screen.getByLabelText(/补充说明/) as HTMLTextAreaElement).value).toBe("外壳有划痕");
  });

  it("submits the server-generated exact confirmation phrase through the only destructive button", () => {
    const onSubmit = vi.fn();
    render(
      <StatefulPanel
        onSubmit={onSubmit}
        request={{
          slot: "refund_confirmation",
          prompt: "请确认退款。",
          orderId: "ORD-1001",
          productName: "AeroPods 降噪耳机",
          amountMinor: 11700,
          currency: "CNY",
          refundTo: "微信支付",
          orderStatusLabel: "已支付，待发货",
          approvalId: "RFD-1",
          confirmationPhrase: "确认退款 RFD-1",
        }}
      />
    );

    expect(screen.getByText("退款去向")).toBeTruthy();
    expect(screen.getByText("微信支付")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认并执行退款" }));
    expect(onSubmit).toHaveBeenCalledWith("确认退款 RFD-1");
  });
});
