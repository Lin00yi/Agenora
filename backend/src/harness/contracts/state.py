"""Shared, serialization-friendly state for graph-backed agent capabilities."""
from __future__ import annotations

from typing import Any, TypedDict


class ToolCallRecord(TypedDict):
    id: str
    name: str
    input: dict[str, Any]
    result: str | None
    latency_ms: int | None
    error: str | None


class RetrievedEvidence(TypedDict, total=False):
    id: str
    source_type: str
    query: str
    text: str
    document_id: str | None
    chunk_id: str | None
    title: str | None
    score: float | None
    kb_id: str | None


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    tool_call_log: list[ToolCallRecord]
    web_search_call_count: int
    web_search_evidence_count: int
    kb_queries: list[dict[str, Any]]
    kb_context: str
    retrieved_evidence: list[RetrievedEvidence]
    retrieval_assessment: dict[str, Any]
    kb_search_done: bool
    query_policy_action: str
    query_policy_reason: str
    query_policy_source: str
    query_policy_latency_ms: int
    prompt_injection_risk: str
    prompt_injection_reasons: list[str]
    rag_suspicious_chunks: int
    rag_filtered_chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    final_report: str | None
    report_streamed: bool
    iterations: int
    cost_usd: float | None
    prompt_trace: dict[str, Any]
    # Serializable, user-safe description of the single-agent capability scope.
    runtime_scope: dict[str, Any]
