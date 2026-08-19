"""Compatibility shim — use ``src.agents`` instead."""

from src.agents.chat import build_chat_graph
from src.agents.rag import build_rag_graph

__all__ = ["build_chat_graph", "build_rag_graph"]
