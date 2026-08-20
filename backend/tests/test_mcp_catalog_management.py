from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.harness.mcp.configuration import (
    McpCatalogAudit,
    McpCatalogConfig,
    McpPluginSetRelease,
    draft_view,
    publish_draft,
    published_snapshot,
    parse_catalog_payload,
    save_draft,
)
from src.harness.mcp import configuration
from src.harness.mcp.catalog import McpCatalog
from src.harness.mcp.manager import McpConnectionManager
from src.platform.persistence.database import Base
from src.settings import Settings


def _catalog() -> dict:
    return {
        "servers": [
            {
                "id": "inventory",
                "transport": "streamable_http",
                "endpoint": "https://inventory.example.test/mcp",
                "secret_headers": {"Authorization": "inventory_token"},
                "allowed_tools": ["lookup_stock"],
                "identity_argument": "actor_id",
            }
        ],
        "contracts": [
            {
                "id": "inventory.lookup",
                "plugin_id": "inventory",
                "agent_tool_name": "lookup_stock",
                "agent_ids": ["orders"],
                "risk": "read",
                "description": "查询库存",
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": {}},
            }
        ],
        "plugins": [
            {"id": "inventory", "contracts": ["inventory.lookup@v1"]}
        ],
        "capabilities": [
            {
                "id": "inventory.lookup",
                "contract_id": "inventory.lookup",
                "server_id": "inventory",
                "tool_name": "lookup_stock",
                "exposed_name": "lookup_stock",
                "agent_id": "orders",
                "risk": "read",
                "description": "查询库存",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }


def _stdio_payload() -> dict:
    return {
                "servers": [
                    {
                        "id": "unsafe",
                        "transport": "stdio",
                        "command": "sh",
                        "allowed_tools": ["run"],
                    }
                ],
                "contracts": [
                    {"id": "unsafe.run", "plugin_id": "unsafe", "agent_tool_name": "run", "agent_ids": ["orders"], "risk": "read"}
                ],
                "plugins": [{"id": "unsafe", "contracts": ["unsafe.run@v1"]}],
                "capabilities": [
                    {
                        "id": "unsafe.run",
                        "contract_id": "unsafe.run",
                        "server_id": "unsafe",
                        "tool_name": "run",
                        "exposed_name": "run",
                        "agent_id": "orders",
                    }
                ],
            }


def test_web_managed_catalog_allows_stdio_only_for_local_development() -> None:
    catalog = parse_catalog_payload(_stdio_payload())
    assert catalog.server("unsafe").transport == "stdio"


def test_web_managed_catalog_rejects_stdio_commands_in_production(monkeypatch) -> None:
    monkeypatch.setattr(configuration, "get_settings", lambda: Settings(app_env="production"))
    with pytest.raises(ValueError, match="available only in local development"):
        parse_catalog_payload(_stdio_payload())


def test_stdio_environment_is_explicit_and_secret_values_use_references() -> None:
    settings = Settings(orders_mcp_service_token="orders-secret")
    manager = McpConnectionManager(catalog=McpCatalog(servers={
        "local": parse_catalog_payload(_stdio_payload()).server("unsafe").model_copy(
            update={
                "inherit_environment": ["PATH", "MISSING"],
                "environment": {"LOG_LEVEL": "debug"},
                "secret_environment": {"API_TOKEN": "orders_mcp_service_token"},
            }
        )
    }, capabilities={}), settings=settings)
    environment = manager._stdio_environment(manager.catalog.server("local"))
    assert environment["LOG_LEVEL"] == "debug"
    assert environment["API_TOKEN"] == "orders-secret"
    assert "MISSING" not in environment


def test_web_managed_catalog_rejects_unimplemented_high_risk_policy() -> None:
    payload = _catalog()
    payload["capabilities"][0]["risk"] = "high_risk_write"
    payload["capabilities"][0]["policy_id"] = "invented_policy"
    payload["contracts"][0]["risk"] = "high_risk_write"
    payload["contracts"][0]["policy_id"] = "invented_policy"
    with pytest.raises(ValueError, match="implemented Host policy"):
        parse_catalog_payload(payload)


@pytest.mark.asyncio
async def test_catalog_draft_publishes_a_version_without_returning_secrets() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            saved = await save_draft(
                session,
                catalog_payload=_catalog(),
                submitted_secrets={"inventory_token": "Bearer private"},
                actor_id="admin-1",
            )
            assert saved["draft_version"] == 1
            assert saved["active_version"] == 0
            await session.commit()

        async with factory() as session:
            published, version = await publish_draft(session, actor_id="admin-1")
            assert version == 1
            assert published["active_version"] == 1
            await session.commit()

        async with factory() as session:
            snapshot = await published_snapshot(session)
            assert snapshot is not None
            version, catalog, secrets = snapshot
            assert version == 1
            assert catalog.capability("inventory.lookup").tool_name == "lookup_stock"
            assert secrets == {"inventory_token": "Bearer private"}
            assert (await session.get(McpCatalogConfig, "platform")) is not None
            assert len(list((await session.execute(select(McpCatalogAudit))).scalars())) == 1
            release = await session.get(McpPluginSetRelease, 1)
            assert release is not None
            assert len(release.checksum) == 64

            view = await draft_view(session, fallback=McpCatalog(servers={}, capabilities={}))
            assert view["active_version"] == 1
            assert "secrets" not in view
            assert view["secret_refs"] == {"inventory_token": True}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plugin_set_releases_are_immutable_and_resolvable_by_version() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            await save_draft(
                session,
                catalog_payload=_catalog(),
                submitted_secrets={"inventory_token": "Bearer v1"},
                actor_id="admin-1",
            )
            await publish_draft(session, actor_id="admin-1")
            await session.commit()

        v2 = _catalog()
        v2["servers"][0]["endpoint"] = "https://inventory-v2.example.test/mcp"
        async with factory() as session:
            await save_draft(
                session,
                catalog_payload=v2,
                submitted_secrets={},
                actor_id="admin-1",
            )
            _, version = await publish_draft(session, actor_id="admin-1")
            assert version == 2
            await session.commit()

        async with factory() as session:
            old = await published_snapshot(session, version=1)
            current = await published_snapshot(session)
            assert old is not None and current is not None
            assert old[0] == 1
            assert old[1].server("inventory").endpoint == "https://inventory.example.test/mcp"
            assert old[2] == {"inventory_token": "Bearer v1"}
            assert current[0] == 2
            assert current[1].server("inventory").endpoint == "https://inventory-v2.example.test/mcp"
    finally:
        await engine.dispose()
