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


class RetrievedEvidence(TypedDict, total=False):
    """One untrusted retrieval item available to the reason node.

    Evidence stays structured until the provider request is assembled so source
    identity survives token trimming and the UI citations can be reconciled
    with exactly what the model received.
    """

    id: str
    source_type: str  # kb | kg
    query: str
    text: str
    document_id: str | None
    chunk_id: str | None
    title: str | None
    score: float | None
    kb_id: str | None


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]           # Anthropic messages history
    pending_tool_calls: list[dict[str, Any]] # tool_use blocks awaiting execution
    tool_call_log: list[ToolCallRecord]      # observable timeline for ThinkingChain UI
    # Server-enforced web-search budget across all tool-loop iterations.
    web_search_call_count: int
    web_search_evidence_count: int
    kb_queries: list[dict[str, Any]]         # deterministic KB search queries from query_policy_node
    # Legacy flattened retrieval text. Retained only for a reversible
    # ``legacy_system`` rollout mode; new requests use ``retrieved_evidence``.
    kb_context: str
    retrieved_evidence: list[RetrievedEvidence]  # untrusted KB/KG evidence for this turn
    kb_search_done: bool                     # guard so KB search runs once per user turn
    query_policy_action: str                 # direct | normalize | expand | skip_kb
    query_policy_reason: str                 # short machine-readable policy reason
    query_policy_source: str                 # rule | llm | fallback
    query_policy_latency_ms: int
    prompt_injection_risk: str               # low | medium | high
    prompt_injection_reasons: list[str]      # direct/indirect injection signals
    rag_suspicious_chunks: int               # KB chunks removed before evidence injection
    # Audit-only rows for filtered RAG/KG chunks (never injected into evidence).
    rag_filtered_chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]]          # structured KB/web source cards for the UI
    final_report: str | None
    report_streamed: bool                     # True when final answer tokens were SSE-streamed live
    iterations: int                          # plan loop guard
    # None means one or more provider calls had no trustworthy configured price.
    cost_usd: float | None
    # Safe per-call token allocation; excludes raw prompts, schemas and content.
    prompt_trace: dict[str, Any]
