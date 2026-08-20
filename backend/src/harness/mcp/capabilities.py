"""Generic ToolRegistry adapters for reviewed MCP capabilities."""
from __future__ import annotations

import json
import time
from typing import Any

from src.harness.mcp.catalog import CapabilityBinding
from src.harness.mcp.manager import McpCapabilityError, McpConnectionManager, get_mcp_manager
from src.harness.tools.base import Tool, ToolRegistry, ToolResult


class McpCapabilityTool(Tool):
    """Expose one Host-approved MCP capability to one execution agent."""

    def __init__(
        self,
        *,
        binding: CapabilityBinding,
        manager: McpConnectionManager,
        actor_id: str,
    ) -> None:
        self.binding = binding
        self.manager = manager
        self.actor_id = actor_id
        self.name = binding.exposed_name
        self.description = binding.description
        self.input_schema = binding.input_schema
        # Runtime guards read this Host-reviewed metadata before dispatching a
        # tool. It is deliberately not generated from MCP server discovery.
        self.risk = binding.risk
        self.policy_id = binding.policy_id

    def trace_metadata(self) -> dict[str, Any]:
        """Expose the catalog's reviewed presentation data to the UI."""
        label = self.binding.display_name or self.binding.description or self.name
        metadata: dict[str, Any] = {
            "kind": "mcp",
            "label": label,
            "server_id": self.binding.server_id,
            "capability_id": self.binding.id,
            "risk": self.binding.risk,
        }
        if self.binding.description and self.binding.description != label:
            metadata["detail"] = self.binding.description
        return metadata

    async def execute(self, **kwargs: Any) -> ToolResult:
        started = time.perf_counter()
        try:
            data = await self.manager.call(self.binding.id, actor_id=self.actor_id, arguments=kwargs)
            status = str(data.get("status") or "")
            error = str(data.get("message") or "MCP request failed") if status in {"error", "unauthorized"} else None
            return ToolResult(
                text=json.dumps(data, ensure_ascii=False),
                raw=data,
                error=error,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except McpCapabilityError as exc:
            return ToolResult(
                text="",
                raw=None,
                error=str(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )


def build_capability_registry(*, agent_id: str, user_id: str | None) -> ToolRegistry:
    """Build an agent-local registry from the current reviewed catalog."""
    registry = ToolRegistry()
    if not user_id:
        return registry
    manager = get_mcp_manager()
    for binding in manager.catalog.capabilities_for_agent(agent_id):
        registry.register(McpCapabilityTool(binding=binding, manager=manager, actor_id=user_id))
    return registry


async def call_capability(
    capability_id: str,
    *,
    user_id: str | None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use a capability outside an agent loop (e.g. durable recovery)."""
    return await get_mcp_manager().call(capability_id, actor_id=user_id, arguments=arguments)
