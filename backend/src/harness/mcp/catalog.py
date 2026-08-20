"""Configuration-backed MCP server and capability catalog.

The catalog is deliberately Host-owned. An MCP server may describe tools, but
it must not decide which agent receives them, which tools are callable, or how
the authenticated identity / service credential is injected.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from src.settings import Settings

McpTransport = Literal["stdio", "streamable_http"]
McpRisk = Literal["read", "write", "high_risk_write"]


class McpServerSpec(BaseModel):
    """One enabled MCP endpoint, without model-controlled credentials."""

    id: str = Field(min_length=1, max_length=80)
    transport: McpTransport
    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    endpoint: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    secret_headers: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    # Arguments created only by the Host. ``actor_id`` is the only supported
    # dynamic identity source today; secret arguments resolve from Settings.
    identity_argument: str | None = None
    secret_arguments: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @model_validator(mode="after")
    def _validate_transport(self) -> "McpServerSpec":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP server requires command")
        if self.transport == "streamable_http" and not self.endpoint:
            raise ValueError("streamable_http MCP server requires endpoint")
        return self


class CapabilityBinding(BaseModel):
    """A reviewed business capability backed by one allowed MCP tool."""

    id: str = Field(min_length=1, max_length=160)
    server_id: str = Field(min_length=1, max_length=80)
    tool_name: str = Field(min_length=1, max_length=160)
    exposed_name: str = Field(min_length=1, max_length=160)
    agent_id: str = Field(min_length=1, max_length=80)
    risk: McpRisk = "read"
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    policy_id: str | None = None

    @field_validator("id", "server_id", "tool_name", "exposed_name", "agent_id")
    @classmethod
    def _strip_identifier(cls, value: str) -> str:
        return value.strip()


@dataclass(frozen=True)
class McpCatalog:
    servers: dict[str, McpServerSpec]
    capabilities: dict[str, CapabilityBinding]

    def server(self, server_id: str) -> McpServerSpec:
        try:
            return self.servers[server_id]
        except KeyError as exc:
            raise KeyError(f"Unknown MCP server: {server_id}") from exc

    def capability(self, capability_id: str) -> CapabilityBinding:
        try:
            return self.capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"Unknown MCP capability: {capability_id}") from exc

    def capabilities_for_agent(self, agent_id: str) -> list[CapabilityBinding]:
        return [
            binding
            for binding in self.capabilities.values()
            if binding.agent_id == agent_id and self.server(binding.server_id).enabled
        ]


def _orders_default_catalog(settings: Settings) -> McpCatalog:
    """Compatibility catalog for the existing local orders service."""
    server = McpServerSpec(
        id="orders",
        transport="stdio",
        enabled=settings.orders_mcp_enabled,
        command="uv",
        args=[
            "run",
            "--directory",
            settings.orders_mcp_server_path,
            "python",
            "-m",
            "mock_orders_mcp.server",
        ],
        cwd=settings.orders_mcp_server_path,
        environment={
            "ORDERS_MCP_DB_PATH": settings.orders_mcp_db_path,
            "ORDERS_MCP_SERVICE_TOKEN": settings.orders_mcp_service_token,
            # The local mock is launched through uv. Keep its cache owned by
            # the mock data directory instead of assuming the process can read
            # a developer's home-directory cache (CI/sandboxes cannot).
            "UV_CACHE_DIR": str(Path(settings.orders_mcp_db_path).parent / ".uv-cache"),
        },
        allowed_tools=[
            "list_orders",
            "get_order",
            "list_refunds",
            "get_refund",
            "prepare_refund",
            "confirm_refund",
        ],
        identity_argument="actor_id",
        secret_arguments={"service_token": "orders_mcp_service_token"},
        timeout_seconds=settings.orders_mcp_timeout_seconds,
    )
    schemas: dict[str, dict[str, Any]] = {
        "list_orders": {"type": "object", "properties": {}, "required": []},
        "get_order": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "订单号"}},
            "required": ["order_id"],
        },
        "list_refunds": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "可选的订单号"}},
            "required": [],
        },
        "get_refund": {
            "type": "object",
            "properties": {"refund_id": {"type": "string", "description": "退款单号或确认单号"}},
            "required": ["refund_id"],
        },
        "prepare_refund": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "reason": {"type": "string", "description": "退款原因"},
                "amount_minor": {"type": "integer", "description": "退款金额，单位分"},
            },
            "required": ["order_id", "reason"],
        },
        "confirm_refund": {
            "type": "object",
            "properties": {
                "approval_id": {"type": "string", "description": "待确认退款单号"},
                "confirmation_text": {"type": "string", "description": "用户的精确确认文本"},
            },
            "required": ["approval_id", "confirmation_text"],
        },
    }
    metadata = {
        "list_orders": ("commerce.orders.list", "查询当前登录用户的订单列表。", "read", None),
        "get_order": ("commerce.orders.get", "按订单号查询当前登录用户的一笔订单。", "read", None),
        "list_refunds": ("commerce.refunds.list", "查询当前登录用户的退款记录。", "read", None),
        "get_refund": ("commerce.refunds.get", "按退款单号或确认单号查询退款状态。", "read", None),
        "prepare_refund": ("commerce.refund.prepare", "创建退款确认单，不会执行退款。", "write", "refund_v1"),
        "confirm_refund": ("commerce.refund.confirm", "执行已确认的退款。", "high_risk_write", "refund_confirmation_v1"),
    }
    capabilities = {
        capability_id: CapabilityBinding(
            id=capability_id,
            server_id=server.id,
            tool_name=tool_name,
            exposed_name=tool_name,
            agent_id="orders",
            description=description,
            risk=risk,  # type: ignore[arg-type]
            policy_id=policy_id,
            input_schema=schemas[tool_name],
        )
        for tool_name, (capability_id, description, risk, policy_id) in metadata.items()
    }
    return McpCatalog(servers={server.id: server}, capabilities=capabilities)


def _catalog_from_json(raw: str) -> McpCatalog:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP_SERVERS_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("MCP_SERVERS_JSON must be an object")
    try:
        servers = [McpServerSpec.model_validate(item) for item in parsed.get("servers", [])]
        capabilities = [CapabilityBinding.model_validate(item) for item in parsed.get("capabilities", [])]
    except ValidationError as exc:
        raise ValueError(f"Invalid MCP catalog: {exc}") from exc
    if not servers:
        raise ValueError("MCP catalog requires at least one server")
    server_map = {server.id: server for server in servers}
    if len(server_map) != len(servers):
        raise ValueError("MCP catalog server ids must be unique")
    capability_map = {binding.id: binding for binding in capabilities}
    if len(capability_map) != len(capabilities):
        raise ValueError("MCP catalog capability ids must be unique")
    exposed_names: set[tuple[str, str]] = set()
    for binding in capabilities:
        server = server_map.get(binding.server_id)
        if server is None:
            raise ValueError(f"Capability {binding.id} refers to unknown server {binding.server_id}")
        if binding.tool_name not in server.allowed_tools:
            raise ValueError(f"Capability {binding.id} refers to tool not allowed by {binding.server_id}")
        if binding.risk == "high_risk_write" and not binding.policy_id:
            raise ValueError(f"High-risk MCP capability {binding.id} requires a Host policy_id")
        key = (binding.agent_id, binding.exposed_name)
        if key in exposed_names:
            raise ValueError(f"Duplicate exposed MCP tool for agent: {binding.agent_id}/{binding.exposed_name}")
        exposed_names.add(key)
    return McpCatalog(servers=server_map, capabilities=capability_map)


def build_mcp_catalog(settings: Settings) -> McpCatalog:
    """Load a reviewed deployment catalog, retaining local orders compatibility."""
    raw = settings.mcp_servers_json.strip()
    return _catalog_from_json(raw) if raw else _orders_default_catalog(settings)
