"""Compatibility shim — use ``src.agents.chat`` instead."""

from src.agents.chat import build_chat_graph

__all__ = ["build_chat_graph"]
