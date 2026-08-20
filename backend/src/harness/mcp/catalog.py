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
    # STDIO plugins receive only explicitly inherited values, rather than the
    # entire API-process environment. This mirrors Codex's env passthrough UI
    # without accidentally leaking unrelated deployment credentials.
    inherit_environment: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    secret_environment: dict[str, str] = Field(default_factory=dict)
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
    # The transport binding can keep a provider-specific id, while agents and
    # policies rely on this versioned business contract.
    contract_id: str | None = Field(default=None, min_length=3, max_length=160)
    contract_version: int = Field(default=1, ge=1, le=1000)
    server_id: str = Field(min_length=1, max_length=80)
    tool_name: str = Field(min_length=1, max_length=160)
    exposed_name: str = Field(min_length=1, max_length=160)
    agent_id: str = Field(min_length=1, max_length=80)
    risk: McpRisk = "read"
    description: str = ""
    # Optional presentation label controlled by the Host/admin catalog. This
    # is intentionally separate from the model-facing description so a newly
    # injected MCP capability can render well without frontend code changes.
    display_name: str | None = Field(default=None, max_length=120)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    policy_id: str | None = None

    @field_validator("id", "server_id", "tool_name", "exposed_name", "agent_id", "display_name")
    @classmethod
    def _strip_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@dataclass(frozen=True)
class McpCatalog:
    servers: dict[str, McpServerSpec]
    capabilities: dict[str, CapabilityBinding]
    contracts: dict[str, Any] | None = None
    plugins: dict[str, Any] | None = None

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

    def contract_for(self, binding: CapabilityBinding):
        from .contracts import CapabilityContract

        contract_id = binding.contract_id or binding.id
        key = f"{contract_id}@v{binding.contract_version}"
        contract = (self.contracts or {}).get(key)
        if not isinstance(contract, CapabilityContract):
            raise KeyError(f"Unknown capability contract: {key}")
        return contract


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
        inherit_environment=["PATH", "LANG", "LC_ALL", "LC_CTYPE"],
        environment={
            "ORDERS_MCP_DB_PATH": settings.orders_mcp_db_path,
            # The local mock is launched through uv. Keep its cache owned by
            # the mock data directory instead of assuming the process can read
            # a developer's home-directory cache (CI/sandboxes cannot).
            "UV_CACHE_DIR": str(Path(settings.orders_mcp_db_path).parent / ".uv-cache"),
        },
        secret_environment={"ORDERS_MCP_SERVICE_TOKEN": "orders_mcp_service_token"},
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
    from .contracts import builtin_contracts, contract_index
    from .plugins import builtin_plugin_manifests, plugin_index

    contracts = contract_index(builtin_contracts())
    plugins = plugin_index(builtin_plugin_manifests())
    metadata = {
        "list_orders": ("commerce.orders.list", "查询当前登录用户的订单列表。", "查询订单", "read", None),
        "get_order": ("commerce.orders.get", "按订单号查询当前登录用户的一笔订单。", "查询订单详情", "read", None),
        "list_refunds": ("commerce.refunds.list", "查询当前登录用户的退款记录。", "查询退款记录", "read", None),
        "get_refund": ("commerce.refunds.get", "按退款单号或确认单号查询退款状态。", "查询退款详情", "read", None),
        "prepare_refund": ("commerce.refund.prepare", "创建退款确认单，不会执行退款。", "创建退款确认单", "write", "refund_v1"),
        "confirm_refund": ("commerce.refund.confirm", "执行已确认的退款。", "执行退款", "high_risk_write", "refund_confirmation_v1"),
    }
    capabilities = {
        capability_id: CapabilityBinding(
            id=capability_id,
            contract_id=capability_id,
            server_id=server.id,
            tool_name=tool_name,
            exposed_name=tool_name,
            agent_id="orders",
            description=description,
            risk=risk,  # type: ignore[arg-type]
            policy_id=policy_id,
            input_schema=contracts[f"{capability_id}@v1"].input_schema,
        )
        for tool_name, (capability_id, description, display_name, risk, policy_id) in metadata.items()
    }
    return McpCatalog(
        servers={server.id: server}, capabilities=capabilities, contracts=contracts, plugins=plugins
    )


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
    # Preserve protocol/security errors ahead of plugin-contract errors: a
    # catalog must never make an unallowlisted or ungoverned tool look valid
    # merely because its plugin manifest is incomplete.
    for binding in capabilities:
        server = server_map.get(binding.server_id)
        if server is None:
            raise ValueError(f"Capability {binding.id} refers to unknown server {binding.server_id}")
        if binding.tool_name not in server.allowed_tools:
            raise ValueError(f"Capability {binding.id} refers to tool not allowed by {binding.server_id}")
        if binding.risk == "high_risk_write" and not binding.policy_id:
            raise ValueError(f"High-risk MCP capability {binding.id} requires a Host policy_id")
    from .contracts import CapabilityContract, builtin_contracts, contract_index
    from .plugins import McpPluginManifest, builtin_plugin_manifests, plugin_index

    try:
        declared_contracts = [
            CapabilityContract.model_validate(item) for item in parsed.get("contracts", [])
        ]
    except ValidationError as exc:
        raise ValueError(f"Invalid MCP capability contracts: {exc}") from exc
    try:
        declared_plugins = [
            McpPluginManifest.model_validate(item) for item in parsed.get("plugins", [])
        ]
        plugins = plugin_index([*builtin_plugin_manifests(), *declared_plugins])
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Invalid MCP plugin manifests: {exc}") from exc
    try:
        contracts = contract_index([*builtin_contracts(), *declared_contracts])
    except ValueError as exc:
        raise ValueError(f"Invalid MCP capability contracts: {exc}") from exc
    for plugin in plugins.values():
        for contract_key in plugin.contracts:
            if contract_key not in contracts:
                raise ValueError(
                    f"Plugin {plugin.key} declares an unknown contract: {contract_key}"
                )
    for contract in contracts.values():
        plugin_key = f"{contract.plugin_id or ''}@v{contract.plugin_version}"
        plugin = plugins.get(plugin_key)
        if contract.plugin_id is None or plugin is None or contract.key not in plugin.contracts:
            raise ValueError(
                f"Capability contract {contract.key} must be supplied by a declared plugin manifest"
            )
    normalised_capabilities: list[CapabilityBinding] = []
    for binding in capabilities:
        # ``id`` remains a compatibility default for pre-plugin catalogs, but
        # unrecognised ids must now declare a contract explicitly.
        binding = binding.model_copy(update={"contract_id": binding.contract_id or binding.id})
        key = f"{binding.contract_id}@v{binding.contract_version}"
        contract = contracts.get(key)
        if contract is None:
            raise ValueError(
                f"Capability {binding.id} must reference a declared contract ({key})"
            )
        if binding.agent_id not in contract.agent_ids:
            raise ValueError(
                f"Capability {binding.id} cannot bind contract {key} to agent {binding.agent_id}"
            )
        if binding.risk != contract.risk or binding.policy_id != contract.policy_id:
            raise ValueError(
                f"Capability {binding.id} risk and policy must match contract {key}"
            )
        if binding.exposed_name != contract.exposed_name:
            raise ValueError(
                f"Capability {binding.id} must expose contract tool name {contract.exposed_name}"
            )
        # Prompt-visible schemas are Host-owned contract schemas, never raw
        # discovery metadata from an MCP server.
        binding = binding.model_copy(update={"input_schema": contract.input_schema})
        normalised_capabilities.append(binding)
    capability_map = {binding.id: binding for binding in normalised_capabilities}
    if len(capability_map) != len(capabilities):
        raise ValueError("MCP catalog capability ids must be unique")
    exposed_names: set[tuple[str, str]] = set()
    for binding in normalised_capabilities:
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
    return McpCatalog(
        servers=server_map, capabilities=capability_map, contracts=contracts, plugins=plugins
    )


def build_mcp_catalog(settings: Settings) -> McpCatalog:
    """Load a reviewed deployment catalog, retaining local orders compatibility."""
    raw = settings.mcp_servers_json.strip()
    return _catalog_from_json(raw) if raw else _orders_default_catalog(settings)
