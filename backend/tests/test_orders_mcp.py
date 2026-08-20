from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.orchestration.planner import rule_route
from src.harness.orchestration.registry import build_default_agent_registry
from src.harness.agents.orders.graph import build_orders_graph
from src.harness.mcp.catalog import build_mcp_catalog
from src.harness.mcp.manager import McpConnectionManager
from src.harness.mcp.orders import refundable_order_options
from src.harness.runtime.agent_loop.call_tools import call_tools_node
from src.harness.tools.base import Tool, ToolRegistry, ToolResult
from src.settings import Settings


class _ConfirmRefundTool(Tool):
    name = "confirm_refund"
    description = "test confirm"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(
            text='{"status":"completed","order_id":"ORD-TEST-1001","refund_no":"RFN-TEST-1","amount_minor":12900,"refund_to":"微信支付"}',
            raw={
                "status": "completed",
                "order_id": "ORD-TEST-1001",
                "refund_no": "RFN-TEST-1",
                "amount_minor": 12900,
                "refund_to": "微信支付",
                "estimated_arrival_at": "2026-08-20T10:00:00+00:00",
            },
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_exact_refund_confirmation_bypasses_llm_and_executes_once() -> None:
    registry = ToolRegistry()
    tool = _ConfirmRefundTool()
    registry.register(tool)
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    graph, _cost = build_orders_graph(registry=registry, emit=emit, user_id="user-1")
    result = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "确认退款 RFD-TEST-1"}],
            "tool_call_log": [],
        }
    )

    assert tool.calls == [
        {"approval_id": "RFD-TEST-1", "confirmation_text": "确认退款 RFD-TEST-1"}
    ]
    assert result["final_report"] == (
        "退款申请已提交。\n订单：ORD-TEST-1001\n退款单号：RFN-TEST-1\n退款金额：12900 分\n退款去向：微信支付\n预计到账：2026-08-20T10:00:00+00:00"
    )
    assert [event["event"] for event in events] == ["tool_start", "tool_end"]


@pytest.mark.asyncio
async def test_stdio_mcp_refund_is_owned_confirmed_and_idempotent(tmp_path) -> None:
    settings = Settings(
        orders_mcp_server_path=str(Path(__file__).resolve().parents[2] / "mock-mcp" / "orders"),
        orders_mcp_db_path=str(tmp_path / "orders.db"),
        orders_mcp_service_token="test-mcp-token",
        orders_mcp_timeout_seconds=10,
    )
    manager = McpConnectionManager(catalog=build_mcp_catalog(settings), settings=settings)
    try:
        discovered = await manager.discover("orders")
        assert {tool["name"] for tool in discovered} == {
            "list_orders",
            "get_order",
            "list_refunds",
            "get_refund",
            "prepare_refund",
            "confirm_refund",
        }
        listing = await manager.call("commerce.orders.list", actor_id="user-alpha")
        assert listing["status"] == "ok"
        assert listing["total"] == 20
        assert {order["status"] for order in listing["orders"]} == {
            "paid",
            "shipped",
            "completed",
            "partial_refunded",
            "refunded",
            "closed",
        }
        assert {order["refund_eligibility"]["eligible"] for order in listing["orders"]} == {True, False}
        order_id = listing["orders"][0]["order_id"]
        first_order = listing["orders"][0]
        assert first_order["items"][0]["product_name"]
        assert first_order["items"][0]["product_url"].startswith("https://demo.agenora.local/")
        assert first_order["payment"]["transaction_masked"]
        assert first_order["refund_eligibility"]["eligible"] is True
        assert all(order["items"][0]["product_url"] for order in listing["orders"])
        assert all(order["payment"]["method"] for order in listing["orders"])
        assert all(order["fulfillment"]["tracking_number"] for order in listing["orders"])
        assert all(order["invoice"]["title"] for order in listing["orders"])
        assert all(order["refund_eligibility"]["deadline_at"] for order in listing["orders"])

        detail = await manager.call("commerce.orders.get", actor_id="user-alpha", arguments={"order_id": order_id})
        assert detail["status"] == "ok"
        assert detail["order"]["fulfillment"]["recipient_phone_masked"] == "138****0621"
        assert detail["order"]["items"][0]["specifications"]

        refunds = await manager.call("commerce.refunds.list", actor_id="user-alpha")
        assert refunds["status"] == "ok"
        assert refunds["total"] == 8
        assert {refund["status"] for refund in refunds["refunds"]} >= {
            "awaiting_confirmation",
            "completed",
            "expired",
        }
        completed_refund = next(refund for refund in refunds["refunds"] if refund["refund_no"])
        historical = await manager.call("commerce.refunds.get", actor_id="user-alpha", arguments={"refund_id": completed_refund["refund_no"]})
        assert historical["status"] == "ok"
        assert historical["refund"]["timeline"]

        refunded_order = next(order for order in listing["orders"] if order["status"] == "refunded")
        assert (await manager.call("commerce.refund.prepare", actor_id="user-alpha", arguments={"order_id": refunded_order["order_id"], "reason": "测试"}))["status"] == "invalid"
        expired_order = next(
            order
            for order in listing["orders"]
            if order["status"] == "completed" and not order["refund_eligibility"]["eligible"]
        )
        assert (await manager.call("commerce.refund.prepare", actor_id="user-alpha", arguments={"order_id": expired_order["order_id"], "reason": "测试"}))["status"] == "invalid"

        pending = await manager.call("commerce.refund.prepare", actor_id="user-alpha", arguments={"order_id": order_id, "reason": "本地测试"})
        assert pending["status"] == "awaiting_confirmation"
        assert pending["refund_to"]
        assert pending["product_name"]
        assert pending["product_url"].startswith("https://demo.agenora.local/")
        too_large = await manager.call(
            "commerce.refund.prepare",
            actor_id="user-alpha",
            arguments={"order_id": order_id, "reason": "金额校验", "amount_minor": first_order["refundable_minor"] + 1},
        )
        assert too_large["status"] == "invalid"
        repeated_pending = await manager.call("commerce.refund.prepare", actor_id="user-alpha", arguments={"order_id": order_id, "reason": "本地测试"})
        assert repeated_pending["approval_id"] == pending["approval_id"]

        assert (await manager.call("commerce.orders.get", actor_id="user-beta", arguments={"order_id": order_id}))["status"] == "not_found"

        completed = await manager.call(
            "commerce.refund.confirm",
            actor_id="user-alpha",
            arguments={"approval_id": pending["approval_id"], "confirmation_text": pending["confirmation_phrase"]},
        )
        assert completed["status"] == "completed"
        assert completed["refund_no"]
        assert completed["estimated_arrival_at"]
        repeated = await manager.call(
            "commerce.refund.confirm",
            actor_id="user-alpha",
            arguments={"approval_id": pending["approval_id"], "confirmation_text": pending["confirmation_phrase"]},
        )
        assert repeated["status"] == "already_completed"
    finally:
        await manager.aclose()


def test_refundable_order_options_only_projects_eligible_order_display_fields() -> None:
    options = refundable_order_options(
        {
            "orders": [
                {
                    "order_id": "ORD-ELIGIBLE",
                    "status": "paid",
                    "status_label": "已支付，待发货",
                    "currency": "CNY",
                    "refund_eligibility": {"eligible": True, "refundable_minor": 12900},
                    "payment": {"method": "微信支付"},
                    "items": [{"product_name": "演示商品", "product_url": "https://demo.agenora.local/p/1"}],
                },
                {
                    "order_id": "ORD-REFUNDED",
                    "refund_eligibility": {"eligible": False, "refundable_minor": 0},
                    "items": [{"product_name": "不可退款商品"}],
                },
            ]
        }
    )

    assert options == [
        {
            "order_id": "ORD-ELIGIBLE",
            "product_name": "演示商品",
            "product_url": "https://demo.agenora.local/p/1",
            "image_url": None,
            "status": "paid",
            "status_label": "已支付，待发货",
            "refundable_minor": 12900,
            "currency": "CNY",
            "refund_to": "微信支付",
        }
    ]


class _ConfirmTool(Tool):
    name = "confirm_refund"
    description = "test"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **_kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult(text="ok", latency_ms=1)


class _UnmanagedHighRiskTool(_ConfirmTool):
    name = "transfer_funds"
    risk = "high_risk_write"
    policy_id = "unknown_policy"


@pytest.mark.asyncio
async def test_refund_execution_is_blocked_without_exact_latest_human_confirmation() -> None:
    tool = _ConfirmTool()
    registry = ToolRegistry()
    registry.register(tool)
    emitted: list[dict] = []

    async def emit(event: dict) -> None:
        emitted.append(event)

    state = {
        "messages": [{"role": "user", "content": "好的，帮我确认吧"}],
        "pending_tool_calls": [
            {
                "id": "call-1",
                "name": "confirm_refund",
                "input": {"approval_id": "RFD-123", "confirmation_text": "确认退款 RFD-123"},
            }
        ],
    }
    out = await call_tools_node(state, registry=registry, emit=emit)

    assert tool.calls == 0
    assert out["messages"][-1]["content"][0]["is_error"] is True
    assert any(event["event"] == "tool_blocked" for event in emitted)


@pytest.mark.asyncio
async def test_high_risk_catalog_tool_is_blocked_without_a_host_execution_policy() -> None:
    tool = _UnmanagedHighRiskTool()
    registry = ToolRegistry()
    registry.register(tool)
    emitted: list[dict] = []

    async def emit(event: dict) -> None:
        emitted.append(event)

    out = await call_tools_node(
        {
            "messages": [{"role": "user", "content": "转账 100 元"}],
            "pending_tool_calls": [{"id": "call-risk", "name": "transfer_funds", "input": {}}],
        },
        registry=registry,
        emit=emit,
    )

    assert tool.calls == 0
    assert out["messages"][-1]["content"][0]["is_error"] is True
    assert emitted[0]["event"] == "tool_blocked"


def test_order_operations_route_to_execution_agent_even_when_kb_is_bound() -> None:
    registry = build_default_agent_registry()
    route = rule_route(has_kb=True, registry=registry, user_query="我要申请退款，订单号是 ORD-1")

    assert route is not None
    assert route["target"] == "orders"
    assert route["tasks"][0]["type"] == "qa_orders"


def test_refund_with_inline_order_id_routes_to_execution_agent() -> None:
    registry = build_default_agent_registry()
    route = rule_route(
        has_kb=False,
        registry=registry,
        user_query="我要这笔订单ORD-d0fb0227-1001退款",
    )

    assert route is not None
    assert route["target"] == "orders"


def test_refund_policy_question_routes_to_kb_not_execution_agent() -> None:
    registry = build_default_agent_registry()
    route = rule_route(has_kb=True, registry=registry, user_query="退款政策是什么？")

    assert route is not None
    assert route["target"] == "rag"
