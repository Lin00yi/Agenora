"""MCP-backed tools for the execution-only orders sub-agent."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.harness.tools.base import Tool, ToolRegistry, ToolResult
from src.settings import get_settings


class OrdersMCPClient:
    """Small stdio client. Identity and service token are injected server-side."""

    def __init__(
        self, *, actor_id: str, server_path: str, db_path: str, service_token: str, timeout_s: float
    ) -> None:
        self.actor_id = actor_id
        self.server_path = server_path
        self.db_path = db_path
        self.service_token = service_token
        self.timeout_s = timeout_s

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server_root = Path(self.server_path).resolve()
        if not (server_root / "pyproject.toml").is_file():
            raise RuntimeError(f"Orders MCP project is missing: {server_root}")
        env = dict(os.environ)
        env.update(
            {
                "ORDERS_MCP_DB_PATH": self.db_path,
                "ORDERS_MCP_SERVICE_TOKEN": self.service_token,
            }
        )
        params = StdioServerParameters(
            # Keep the mock server's dependencies and lockfile outside the
            # backend environment. The Host only owns the MCP client protocol.
            command="uv",
            args=["run", "--directory", str(server_root), "python", "-m", "mock_orders_mcp.server"],
            env=env,
            cwd=str(server_root),
        )
        payload = {**arguments, "actor_id": self.actor_id, "service_token": self.service_token}
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, payload, read_timeout_seconds=self.timeout_s)
        data = getattr(result, "structuredContent", None)
        if isinstance(data, dict):
            return data
        content = getattr(result, "content", []) or []
        for item in content:
            raw = getattr(item, "text", None)
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        if bool(getattr(result, "isError", False)):
            return {"status": "error", "message": "MCP tool execution failed."}
        return {"status": "error", "message": "MCP tool returned no structured result."}


class _OrdersMCPTool(Tool):
    tool_name: str

    def __init__(self, client: OrdersMCPClient) -> None:
        self.client = client

    async def execute(self, **kwargs: Any) -> ToolResult:
        started = time.perf_counter()
        try:
            data = await self.client.call(self.tool_name, kwargs)
            error = None if data.get("status") not in {"error", "unauthorized"} else str(data.get("message") or "MCP request failed")
            return ToolResult(
                text=json.dumps(data, ensure_ascii=False),
                raw=data,
                error=error,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(text="", raw=None, error=f"Orders MCP unavailable: {exc}", latency_ms=int((time.perf_counter() - started) * 1000))


class ListOrdersTool(_OrdersMCPTool):
    name = "list_orders"
    tool_name = "list_orders"
    description = "查询当前登录用户的订单列表。"
    input_schema = {"type": "object", "properties": {}, "required": []}


class GetOrderTool(_OrdersMCPTool):
    name = "get_order"
    tool_name = "get_order"
    description = "按订单号查询当前登录用户的一笔订单。"
    input_schema = {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "订单号"}},
        "required": ["order_id"],
    }


class ListRefundsTool(_OrdersMCPTool):
    name = "list_refunds"
    tool_name = "list_refunds"
    description = "查询当前登录用户的退款记录；可按订单号筛选。"
    input_schema = {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "可选的订单号"}},
        "required": [],
    }


class GetRefundTool(_OrdersMCPTool):
    name = "get_refund"
    tool_name = "get_refund"
    description = "按退款单号或退款确认单号查询退款状态和时间线。"
    input_schema = {
        "type": "object",
        "properties": {"refund_id": {"type": "string", "description": "退款单号或确认单号"}},
        "required": ["refund_id"],
    }


class PrepareRefundTool(_OrdersMCPTool):
    name = "prepare_refund"
    tool_name = "prepare_refund"
    description = "创建退款确认单，不会执行退款；必须先有订单号和退款原因。"
    input_schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "订单号"},
            "reason": {"type": "string", "description": "退款原因"},
            "amount_minor": {"type": "integer", "description": "退款金额，单位分；缺省为可退全额"},
        },
        "required": ["order_id", "reason"],
    }


class ConfirmRefundTool(_OrdersMCPTool):
    name = "confirm_refund"
    tool_name = "confirm_refund"
    description = "执行已创建的退款确认单。仅当用户最新一条消息精确为“确认退款 <approval_id>”时可调用。"
    input_schema = {
        "type": "object",
        "properties": {
            "approval_id": {"type": "string", "description": "待确认退款单号"},
            "confirmation_text": {"type": "string", "description": "用户最新消息中的精确确认文本"},
        },
        "required": ["approval_id", "confirmation_text"],
    }


def build_orders_registry(*, user_id: str | None) -> ToolRegistry:
    registry = ToolRegistry()
    settings = get_settings()
    if not settings.orders_mcp_enabled or not user_id:
        return registry
    client = OrdersMCPClient(
        actor_id=user_id,
        server_path=settings.orders_mcp_server_path,
        db_path=settings.orders_mcp_db_path,
        service_token=settings.orders_mcp_service_token,
        timeout_s=settings.orders_mcp_timeout_seconds,
    )
    registry.register(ListOrdersTool(client))
    registry.register(GetOrderTool(client))
    registry.register(ListRefundsTool(client))
    registry.register(GetRefundTool(client))
    registry.register(PrepareRefundTool(client))
    registry.register(ConfirmRefundTool(client))
    return registry
