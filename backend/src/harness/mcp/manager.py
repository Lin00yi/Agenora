"""Host-owned MCP connections and reviewed capability dispatch.

MCP servers expose a protocol.  This module is the boundary that turns a
reviewed catalog entry into a callable capability: the model can supply only
the business arguments; authenticated identity and deployment credentials are
added here and never appear in a tool schema.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.harness.mcp.catalog import McpCatalog, McpServerSpec, build_mcp_catalog
from src.settings import Settings, get_settings


class McpCapabilityError(RuntimeError):
    """A safe error returned at the Host/MCP capability boundary."""


@dataclass
class _Connection:
    stack: AsyncExitStack
    session: ClientSession
    lock: asyncio.Lock


def _result_payload(result: Any) -> dict[str, Any]:
    """Normalize structured MCP results without trusting free-form text."""
    data = getattr(result, "structuredContent", None)
    if isinstance(data, dict):
        return data
    for item in getattr(result, "content", []) or []:
        raw = getattr(item, "text", None)
        if not isinstance(raw, str):
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    if bool(getattr(result, "isError", False)):
        return {"status": "error", "message": "MCP tool execution failed."}
    return {"status": "error", "message": "MCP tool returned no structured result."}


class McpConnectionManager:
    """Lazily manages one initialized connection for every configured server."""

    def __init__(self, *, catalog: McpCatalog, settings: Settings) -> None:
        self.catalog = catalog
        self.settings = settings
        self._secrets = self._load_secret_values(settings.mcp_secrets_json)
        self._connections: dict[str, _Connection] = {}
        self._create_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _load_secret_values(raw: str) -> dict[str, str]:
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpCapabilityError("MCP_SECRETS_JSON must be valid JSON.") from exc
        if not isinstance(parsed, dict) or any(not isinstance(value, str) for value in parsed.values()):
            raise McpCapabilityError("MCP_SECRETS_JSON must be an object of string values.")
        return parsed

    def _secret_value(self, reference: str, *, server_id: str) -> str:
        value = self._secrets.get(reference)
        if value is None:
            value = getattr(self.settings, reference, None)
        if not isinstance(value, str) or not value:
            raise McpCapabilityError(
                f"MCP server {server_id} is missing its Host credential configuration."
            )
        return value

    def _host_headers(self, server: McpServerSpec) -> dict[str, str]:
        headers = dict(server.headers)
        for header, secret_reference in server.secret_headers.items():
            headers[header] = self._secret_value(secret_reference, server_id=server.id)
        return headers

    def _create_lock(self, server_id: str) -> asyncio.Lock:
        lock = self._create_locks.get(server_id)
        if lock is None:
            lock = asyncio.Lock()
            self._create_locks[server_id] = lock
        return lock

    async def _open(self, server: McpServerSpec) -> _Connection:
        stack = AsyncExitStack()
        try:
            if server.transport == "stdio":
                environment = dict(os.environ)
                environment.update(server.environment)
                params = StdioServerParameters(
                    command=server.command or "",
                    args=server.args,
                    env=environment,
                    cwd=server.cwd,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                # ``mcp`` uses its own httpx2 compatibility package.  The
                # client is stack-owned here because a caller-provided client
                # is intentionally not closed by streamable_http_client.
                import httpx2
                from mcp.client.streamable_http import streamable_http_client

                http_client = await stack.enter_async_context(
                    httpx2.AsyncClient(headers=self._host_headers(server) or None)
                )
                read, write = await stack.enter_async_context(
                    streamable_http_client(server.endpoint or "", http_client=http_client)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return _Connection(stack=stack, session=session, lock=asyncio.Lock())
        except Exception:
            await stack.aclose()
            raise

    async def _connection(self, server: McpServerSpec) -> _Connection:
        existing = self._connections.get(server.id)
        if existing is not None:
            return existing
        async with self._create_lock(server.id):
            existing = self._connections.get(server.id)
            if existing is None:
                existing = await self._open(server)
                self._connections[server.id] = existing
            return existing

    async def _invalidate(self, server_id: str, connection: _Connection | None = None) -> None:
        current = self._connections.get(server_id)
        if current is None or (connection is not None and current is not connection):
            return
        self._connections.pop(server_id, None)
        await current.stack.aclose()

    def _host_arguments(
        self,
        server: McpServerSpec,
        *,
        actor_id: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Reject attempts to override Host-only identity/credential fields."""
        protected = set(server.secret_arguments)
        if server.identity_argument:
            protected.add(server.identity_argument)
        overridden = protected.intersection(arguments)
        if overridden:
            raise McpCapabilityError(
                f"Host-managed MCP argument cannot be supplied: {sorted(overridden)[0]}"
            )
        payload = dict(arguments)
        if server.identity_argument:
            if not actor_id:
                raise McpCapabilityError("Authenticated identity is required for this MCP capability.")
            payload[server.identity_argument] = actor_id
        for argument, setting_name in server.secret_arguments.items():
            payload[argument] = self._secret_value(setting_name, server_id=server.id)
        return payload

    async def call(
        self,
        capability_id: str,
        *,
        actor_id: str | None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke exactly one reviewed capability.

        Invalidation is deliberately not followed by an automatic replay.  A
        write can have committed remotely even if its response connection died;
        business idempotency and the caller's explicit recovery flow decide
        what happens next.
        """
        binding = self.catalog.capability(capability_id)
        server = self.catalog.server(binding.server_id)
        if not server.enabled:
            raise McpCapabilityError(f"MCP server {server.id} is disabled.")
        if binding.tool_name not in server.allowed_tools:
            raise McpCapabilityError(
                f"MCP capability {binding.id} is not allowed by server {server.id}."
            )
        payload = self._host_arguments(server, actor_id=actor_id, arguments=arguments or {})
        connection = await self._connection(server)
        try:
            async with connection.lock:
                result = await connection.session.call_tool(
                    binding.tool_name,
                    payload,
                    read_timeout_seconds=server.timeout_seconds,
                )
        except Exception as exc:
            await self._invalidate(server.id, connection)
            raise McpCapabilityError(f"MCP server {server.id} is unavailable.") from exc
        return _result_payload(result)

    async def discover(self, server_id: str) -> list[dict[str, Any]]:
        """Return safe metadata for the server's Host-allowlisted tools."""
        server = self.catalog.server(server_id)
        if not server.enabled:
            return []
        connection = await self._connection(server)
        try:
            async with connection.lock:
                response = await connection.session.list_tools()
        except Exception as exc:
            await self._invalidate(server.id, connection)
            raise McpCapabilityError(f"MCP server {server.id} is unavailable.") from exc
        tools: list[dict[str, Any]] = []
        for tool in getattr(response, "tools", []) or []:
            name = getattr(tool, "name", None)
            if not isinstance(name, str) or name not in server.allowed_tools:
                continue
            schema = getattr(tool, "inputSchema", None)
            tools.append(
                {
                    "name": name,
                    "description": getattr(tool, "description", "") or "",
                    "input_schema": schema if isinstance(schema, dict) else {},
                }
            )
        return tools

    async def health(self, server_id: str) -> dict[str, Any]:
        started = perf_counter()
        try:
            tools = await self.discover(server_id)
            return {
                "server_id": server_id,
                "healthy": True,
                "tool_count": len(tools),
                "latency_ms": int((perf_counter() - started) * 1000),
            }
        except McpCapabilityError as exc:
            return {
                "server_id": server_id,
                "healthy": False,
                "error": str(exc),
                "latency_ms": int((perf_counter() - started) * 1000),
            }

    async def aclose(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in connections:
            await connection.stack.aclose()


_default_manager: McpConnectionManager | None = None


def get_mcp_manager() -> McpConnectionManager:
    """Application-wide lazy manager, closed by the FastAPI lifespan."""
    global _default_manager
    if _default_manager is None:
        settings = get_settings()
        _default_manager = McpConnectionManager(catalog=build_mcp_catalog(settings), settings=settings)
    return _default_manager


async def close_mcp_manager() -> None:
    global _default_manager
    if _default_manager is not None:
        await _default_manager.aclose()
        _default_manager = None
