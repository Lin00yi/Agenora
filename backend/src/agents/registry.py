"""Compatibility exports for the harness-owned capability registry."""

from src.harness.orchestration.registry import (
    AgentRegistry,
    AgentSpec,
    Emitter,
    RuntimeDeps,
    build_default_agent_registry,
)

__all__ = [
    "AgentRegistry",
    "AgentSpec",
    "Emitter",
    "RuntimeDeps",
    "build_default_agent_registry",
]
