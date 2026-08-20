"""Orders domain projections over generic reviewed MCP capabilities.

This module intentionally contains no subprocess, endpoint or credential
knowledge. The MCP catalog/manager decide how a capability reaches an MCP
server; orders only shapes data for the supervisor's human-intervention UI.
"""
from __future__ import annotations

from typing import Any

from src.harness.mcp.capabilities import build_capability_registry, call_capability
from src.harness.mcp.manager import McpCapabilityError
from src.harness.mcp.manager import McpConnectionManager
from src.harness.tools.base import ToolRegistry

LIST_ORDERS_CAPABILITY = "commerce.orders.list"
GET_REFUND_CAPABILITY = "commerce.refunds.get"


def refundable_order_options(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project only safe, UI-relevant fields from the authoritative order list."""
    options: list[dict[str, Any]] = []
    for order in payload.get("orders") or []:
        if not isinstance(order, dict):
            continue
        eligibility = order.get("refund_eligibility")
        if not isinstance(eligibility, dict) or eligibility.get("eligible") is not True:
            continue
        order_id = order.get("order_id")
        items = order.get("items")
        first_item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        payment = order.get("payment")
        if not isinstance(order_id, str) or not order_id:
            continue
        options.append(
            {
                "order_id": order_id,
                "product_name": first_item.get("product_name") or "未命名商品",
                "product_url": first_item.get("product_url"),
                "image_url": first_item.get("image_url"),
                "status": order.get("status"),
                "status_label": order.get("status_label") or order.get("status"),
                "refundable_minor": eligibility.get("refundable_minor"),
                "currency": order.get("currency"),
                "refund_to": payment.get("method") if isinstance(payment, dict) else None,
            }
        )
    return options


async def list_refundable_order_options(
    *, user_id: str | None, plugin_set_version: int | None = None
) -> list[dict[str, Any]]:
    """Read eligible orders through the Host-reviewed read capability."""
    if not user_id:
        return []
    try:
        payload = await call_capability(
            LIST_ORDERS_CAPABILITY, user_id=user_id, plugin_set_version=plugin_set_version
        )
    except (KeyError, McpCapabilityError):
        return []
    return refundable_order_options(payload)


async def get_refund(
    *, user_id: str | None, refund_id: str, plugin_set_version: int | None = None
) -> dict[str, Any]:
    """Read a refund record for durable post-confirmation recovery."""
    return await call_capability(
        GET_REFUND_CAPABILITY,
        user_id=user_id,
        arguments={"refund_id": refund_id},
        plugin_set_version=plugin_set_version,
    )


def build_orders_registry(
    *, user_id: str | None, manager: McpConnectionManager | None = None
) -> ToolRegistry:
    """Compatibility facade for the orders graph's current tool names."""
    return build_capability_registry(agent_id="orders", user_id=user_id, manager=manager)
