"""Compatibility shims for the pre-runtime agent package.

Prefer:
  ``from src.runtime import build_supervisor_graph``
  ``from src.agents.chat import build_chat_graph``
  ``from src.agents.rag import build_rag_graph``
"""

from src.agents import build_chat_graph, build_rag_graph
from src.runtime import build_supervisor_graph
from src.runtime.registry import AgentRegistry, AgentSpec, build_default_agent_registry

__all__ = [
    "AgentRegistry",
    "AgentSpec",
    "build_chat_graph",
    "build_rag_graph",
    "build_default_agent_registry",
    "build_supervisor_graph",
]
