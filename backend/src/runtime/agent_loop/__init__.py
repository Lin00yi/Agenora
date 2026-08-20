"""LangGraph nodes: query_policy, kb_search, reason, call_tools.

Public re-exports preserve ``from src.runtime.agent_loop import X`` for graph, app, and tests.
"""
from __future__ import annotations

# Re-exported so tests can monkeypatch ``src.runtime.agent_loop.get_client`` as before.
from src.adapters.llm import get_client

from .call_tools import call_tools_node
from .constants import EMPTY_ANSWER_FALLBACK, MAX_ITERATIONS
from .kb_search import kb_search_node
from .prompts_budget import allocate_provider_context, build_effective_system_prompt
from .query_policy import _rule_query_policy, query_policy_node
from .reason import reason_node
from .routing import should_continue, should_search_kb

__all__ = [
    "EMPTY_ANSWER_FALLBACK",
    "MAX_ITERATIONS",
    "allocate_provider_context",
    "build_effective_system_prompt",
    "call_tools_node",
    "get_client",
    "kb_search_node",
    "query_policy_node",
    "reason_node",
    "should_continue",
    "should_search_kb",
    "_rule_query_policy",
]
