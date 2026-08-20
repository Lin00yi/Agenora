from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.orchestration.planner import rule_route
from src.harness.orchestration.registry import build_default_agent_registry
from src.harness.runtime.agent_loop.call_tools import call_tools_node
from src.harness.tools.base import Tool, ToolRegistry, ToolResult
from src.harness.mcp.orders import OrdersMCPClient


@pytest.mark.asyncio
async def test_stdio_mcp_refund_is_owned_confirmed_and_idempotent(tmp_path) -> None:
    client = OrdersMCPClient(
        actor_id="user-alpha",
        server_path=str(Path(__file__).resolve().parents[2] / "mock-mcp" / "orders"),
        db_path=str(tmp_path / "orders.db"),
        service_token="test-mcp-token",
        timeout_s=10,
    )
    # The subprocess receives this through the client environment.
    import os

    old_token = os.environ.get("ORDERS_MCP_SERVICE_TOKEN")
    os.environ["ORDERS_MCP_SERVICE_TOKEN"] = "test-mcp-token"
    try:
        listing = await client.call("list_orders", {})
        assert listing["status"] == "ok"
        order_id = listing["orders"][0]["order_id"]

        pending = await client.call("prepare_refund", {"order_id": order_id, "reason": "本地测试"})
        assert pending["status"] == "awaiting_confirmation"

        wrong_user = OrdersMCPClient(
            actor_id="user-beta",
            server_path=str(Path(__file__).resolve().parents[2] / "mock-mcp" / "orders"),
            db_path=str(tmp_path / "orders.db"),
            service_token="test-mcp-token",
            timeout_s=10,
        )
        assert (await wrong_user.call("get_order", {"order_id": order_id}))["status"] == "not_found"

        completed = await client.call(
            "confirm_refund",
            {"approval_id": pending["approval_id"], "confirmation_text": pending["confirmation_phrase"]},
        )
        assert completed["status"] == "completed"
        repeated = await client.call(
            "confirm_refund",
            {"approval_id": pending["approval_id"], "confirmation_text": pending["confirmation_phrase"]},
        )
        assert repeated["status"] == "already_completed"
    finally:
        if old_token is None:
            os.environ.pop("ORDERS_MCP_SERVICE_TOKEN", None)
        else:
            os.environ["ORDERS_MCP_SERVICE_TOKEN"] = old_token


class _ConfirmTool(Tool):
    name = "confirm_refund"
    description = "test"
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **_kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult(text="ok", latency_ms=1)


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
