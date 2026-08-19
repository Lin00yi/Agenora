"""Compatibility shim — use ``src.runtime.registry`` instead."""

from src.runtime.registry import *  # noqa: F403
from src.runtime.registry import AgentRegistry, AgentSpec, RuntimeDeps, build_default_agent_registry

__all__ = ["AgentRegistry", "AgentSpec", "RuntimeDeps", "build_default_agent_registry"]
