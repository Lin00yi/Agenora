"""Compatibility shim — use ``src.runtime`` instead."""

from src.runtime import (
    SupervisorState,
    build_supervisor_graph,
    choose_initial_agent,
    resolve_agent_route,
    should_handoff_to_chat,
)

__all__ = [
    "SupervisorState",
    "build_supervisor_graph",
    "choose_initial_agent",
    "resolve_agent_route",
    "should_handoff_to_chat",
]
