"""Supervisor state contract shared across graph-backed capabilities."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from .dag import TaskDag

SupervisorDecision = Literal["dispatch", "finish", "human_input"]


class SupervisorState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    iterations: int
    tool_call_log: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    prompt_injection_risk: str
    prompt_injection_reasons: list[str]
    rag_suspicious_chunks: int
    rag_filtered_chunks: list[dict[str, Any]]
    web_search_call_count: int
    web_search_evidence_count: int
    kb_queries: list[dict[str, Any]]
    kb_context: str
    retrieved_evidence: list[dict[str, Any]]
    kb_search_done: bool
    query_policy_action: str
    query_policy_reason: str
    query_policy_source: str
    query_policy_latency_ms: int
    final_report: str | None
    report_streamed: bool
    cost_usd: float | None
    prompt_trace: dict[str, Any]
    kb_id: str | None
    base_messages: list[dict[str, Any]]
    active_agent: str | None
    last_agent: str | None
    agent_results: dict[str, Any]
    route_reason: str
    route_source: str
    route_confidence: str
    intent_assessment: dict[str, Any]
    human_inputs: dict[str, str]
    human_required_slots: list[str]
    human_gate_resumed: bool
    pending_confirmation: dict[str, Any] | None
    handoff_count: int
    supervisor_trace: list[dict[str, Any]]
    supervisor_decision: SupervisorDecision
    task_dag: TaskDag
    task_status: dict[str, str]
    active_task_id: str | None
    active_tasks: list[dict[str, Any]]
    kb_auto_route: dict[str, Any] | None
