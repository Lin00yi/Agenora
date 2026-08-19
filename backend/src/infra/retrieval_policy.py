"""Compatibility shim — use ``src.retrieval.policy`` instead."""

from src.retrieval.policy import KBRetrievalPolicy, resolve_kb_retrieval_policy

__all__ = ["KBRetrievalPolicy", "resolve_kb_retrieval_policy"]
