"""Backward-compatible import path for the main (supervisor) agent.

Prefer: ``from src.agent.main_agent import build_supervisor_graph``
"""
from src.agent.main_agent.router import choose_initial_agent, resolve_agent_route
from src.agent.main_agent.supervisor import (
    SupervisorState,
    build_supervisor_graph,
    should_handoff_to_chat,
)

__all__ = [
    "SupervisorState",
    "build_supervisor_graph",
    "choose_initial_agent",
    "resolve_agent_route",
    "should_handoff_to_chat",
]
