"""Declarative MCP plugin manifests.

This is intentionally metadata-only.  A database publication may select a
reviewed adapter release, but it cannot upload/execute arbitrary Python code.
Code-bearing agent extensions remain deployment-signed artifacts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


PluginKind = Literal["mcp_adapter", "agent_extension"]


class McpPluginManifest(BaseModel):
    id: str = Field(min_length=3, max_length=120)
    version: int = Field(default=1, ge=1, le=1000)
    kind: PluginKind = "mcp_adapter"
    description: str = Field(default="", max_length=1000)
    contracts: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned or " " in cleaned:
            raise ValueError("plugin id must be a non-empty identifier")
        return cleaned

    @property
    def key(self) -> str:
        return f"{self.id}@v{self.version}"


def builtin_plugin_manifests() -> list[McpPluginManifest]:
    return [
        McpPluginManifest(
            id="builtin.orders",
            version=1,
            description="Built-in orders agent capability contracts",
            contracts=[
                "commerce.orders.list@v1",
                "commerce.orders.get@v1",
                "commerce.refunds.list@v1",
                "commerce.refunds.get@v1",
                "commerce.refund.prepare@v1",
                "commerce.refund.confirm@v1",
            ],
        )
    ]


def plugin_index(manifests: list[McpPluginManifest]) -> dict[str, McpPluginManifest]:
    indexed: dict[str, McpPluginManifest] = {}
    for manifest in manifests:
        previous = indexed.get(manifest.key)
        if previous is not None and previous != manifest:
            raise ValueError("plugin id and version pairs must be unique")
        indexed[manifest.key] = manifest
    return indexed
