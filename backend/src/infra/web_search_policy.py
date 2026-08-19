"""Compatibility shim — use ``src.retrieval.policy`` instead."""

from src.retrieval.policy import WebSearchMode, WebSearchPolicy, resolve_web_search_policy

__all__ = ["WebSearchMode", "WebSearchPolicy", "resolve_web_search_policy"]
