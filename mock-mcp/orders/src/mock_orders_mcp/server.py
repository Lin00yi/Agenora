"""Local stdio MCP server for the sample orders and refunds domain."""
from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .service import OrdersService


def _authorize(actor_id: str, service_token: str) -> str | None:
    expected = os.getenv("ORDERS_MCP_SERVICE_TOKEN", "")
    if not expected or service_token != expected:
        return "MCP service authentication failed."
    if not actor_id.strip():
        return "Authenticated actor is required."
    return None


def _service() -> OrdersService:
    return OrdersService(os.getenv("ORDERS_MCP_DB_PATH", "data/orders.db"))


server = MCPServer(
    "agenora-orders",
    title="Agenora local orders service",
    description="Local demo orders and two-step refund execution service.",
)


@server.tool(description="List only the authenticated user's orders.", structured_output=True)
def list_orders(actor_id: str, service_token: str) -> dict[str, Any]:
    error = _authorize(actor_id, service_token)
    return {"status": "unauthorized", "message": error} if error else _service().list_orders(actor_id)


@server.tool(description="Read one order owned by the authenticated user.", structured_output=True)
def get_order(actor_id: str, service_token: str, order_id: str) -> dict[str, Any]:
    error = _authorize(actor_id, service_token)
    return {"status": "unauthorized", "message": error} if error else _service().get_order(actor_id, order_id)


@server.tool(description="Prepare but never execute a refund; returns a confirmation phrase.", structured_output=True)
def prepare_refund(
    actor_id: str,
    service_token: str,
    order_id: str,
    reason: str,
    amount_minor: int | None = None,
) -> dict[str, Any]:
    error = _authorize(actor_id, service_token)
    return (
        {"status": "unauthorized", "message": error}
        if error
        else _service().prepare_refund(actor_id, order_id, reason, amount_minor)
    )


@server.tool(description="Execute a prepared refund after explicit confirmation.", structured_output=True)
def confirm_refund(
    actor_id: str, service_token: str, approval_id: str, confirmation_text: str
) -> dict[str, Any]:
    error = _authorize(actor_id, service_token)
    return (
        {"status": "unauthorized", "message": error}
        if error
        else _service().confirm_refund(actor_id, approval_id, confirmation_text)
    )


if __name__ == "__main__":
    server.run(transport="stdio")
