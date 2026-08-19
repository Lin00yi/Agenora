"""Compatibility facade — use ``src.agents`` instead."""

from src.agents import build_chat_graph, build_graph, build_rag_graph

__all__ = ["build_chat_graph", "build_rag_graph", "build_graph"]
