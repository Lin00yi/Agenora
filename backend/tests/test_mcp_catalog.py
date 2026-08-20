from __future__ import annotations

import pytest

from src.harness.mcp.catalog import build_mcp_catalog
from src.harness.mcp.manager import McpCapabilityError, McpConnectionManager
from src.settings import Settings


def test_default_catalog_keeps_orders_capabilities_and_host_policy() -> None:
    catalog = build_mcp_catalog(Settings())

    assert catalog.server("orders").transport == "stdio"
    assert catalog.capability("commerce.refund.confirm").risk == "high_risk_write"
    assert catalog.capability("commerce.refund.confirm").policy_id == "refund_confirmation_v1"
    assert {item.exposed_name for item in catalog.capabilities_for_agent("orders")} == {
        "list_orders",
        "get_order",
        "list_refunds",
        "get_refund",
        "prepare_refund",
        "confirm_refund",
    }


def test_catalog_requires_a_capability_tool_to_be_allowlisted() -> None:
    settings = Settings(
        mcp_servers_json=(
            '{"servers":[{"id":"inventory","transport":"streamable_http",'
            '"endpoint":"https://mcp.example.test/mcp","allowed_tools":["lookup"]}],'
            '"capabilities":[{"id":"inventory.delete","server_id":"inventory",'
            '"tool_name":"delete","exposed_name":"delete","agent_id":"inventory"}]}'
        )
    )

    with pytest.raises(ValueError, match="not allowed"):
        build_mcp_catalog(settings)


def test_catalog_requires_host_policy_for_high_risk_write() -> None:
    settings = Settings(
        mcp_servers_json=(
            '{"servers":[{"id":"payments","transport":"streamable_http",'
            '"endpoint":"https://mcp.example.test/mcp","allowed_tools":["pay"]}],'
            '"capabilities":[{"id":"payments.pay","server_id":"payments",'
            '"tool_name":"pay","exposed_name":"pay","agent_id":"orders",'
            '"risk":"high_risk_write"}]}'
        )
    )

    with pytest.raises(ValueError, match="requires a Host policy_id"):
        build_mcp_catalog(settings)


def test_custom_http_server_can_bind_capability_and_host_secret_header() -> None:
    settings = Settings(
        mcp_servers_json=(
            '{"servers":[{"id":"inventory","transport":"streamable_http",'
            '"endpoint":"https://mcp.example.test/mcp","allowed_tools":["lookup"],'
            '"identity_argument":"user_id","secret_headers":{"Authorization":"inventory_token"}}],'
            '"capabilities":[{"id":"inventory.lookup","server_id":"inventory",'
            '"tool_name":"lookup","exposed_name":"lookup_inventory","agent_id":"orders",'
            '"description":"查询库存","input_schema":{"type":"object","properties":{}}}]}'
        ),
        mcp_secrets_json='{"inventory_token":"Bearer test-token"}',
    )
    manager = McpConnectionManager(catalog=build_mcp_catalog(settings), settings=settings)
    server = manager.catalog.server("inventory")

    assert manager._host_headers(server) == {"Authorization": "Bearer test-token"}
    assert manager.catalog.capabilities_for_agent("orders")[0].exposed_name == "lookup_inventory"


def test_manager_rejects_model_override_of_host_identity_and_secret() -> None:
    settings = Settings(orders_mcp_service_token="test-service-token")
    manager = McpConnectionManager(catalog=build_mcp_catalog(settings), settings=settings)
    server = manager.catalog.server("orders")

    with pytest.raises(McpCapabilityError, match="actor_id"):
        manager._host_arguments(server, actor_id="user-a", arguments={"actor_id": "user-b"})
    with pytest.raises(McpCapabilityError, match="service_token"):
        manager._host_arguments(server, actor_id="user-a", arguments={"service_token": "forged"})

    assert manager._host_arguments(server, actor_id="user-a", arguments={"order_id": "ORD-1"}) == {
        "order_id": "ORD-1",
        "actor_id": "user-a",
        "service_token": "test-service-token",
    }
