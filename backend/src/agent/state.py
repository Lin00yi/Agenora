"""Agent state types."""
from __future__ import annotations

from typing import Any, TypedDict


class ToolCallRecord(TypedDict):
    id: str
    name: str
    input: dict[str, Any]
    result: str | None
    latency_ms: int | None
    error: str | None


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]           # Anthropic messages history
    pending_tool_calls: list[dict[str, Any]] # tool_use blocks awaiting execution
    tool_call_log: list[ToolCallRecord]      # observable timeline for ThinkingChain UI
    kb_queries: list[dict[str, Any]]         # deterministic KB search queries from query_rewrite_node
    kb_context: str                          # merged KB search context for the reason node
    kb_search_done: bool                     # guard so KB search runs once per user turn
    final_report: str | None
    iterations: int                          # plan loop guard
    cost_usd: float
