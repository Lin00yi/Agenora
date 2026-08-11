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
    kb_queries: list[dict[str, Any]]         # deterministic KB search queries from query_policy_node
    kb_context: str                          # merged KB search context for the reason node
    kb_search_done: bool                     # guard so KB search runs once per user turn
    query_policy_action: str                 # direct | normalize | expand | skip_kb
    query_policy_reason: str                 # short machine-readable policy reason
    query_policy_source: str                 # rule | llm | fallback
    query_policy_latency_ms: int
    prompt_injection_risk: str               # low | medium | high
    prompt_injection_reasons: list[str]      # direct/indirect injection signals
    rag_suspicious_chunks: int               # KB chunks removed before kb_context
    # Audit-only rows for filtered RAG/KG chunks (never injected into kb_context).
    rag_filtered_chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]]          # structured KB/web source cards for the UI
    final_report: str | None
    report_streamed: bool                     # True when final answer tokens were SSE-streamed live
    iterations: int                          # plan loop guard
    cost_usd: float
