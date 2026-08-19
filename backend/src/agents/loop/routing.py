"""Routing helpers for the LangGraph agent loop."""
from __future__ import annotations

from src.agents.state import AgentState


def should_continue(state: AgentState) -> str:
    if state.get("final_report"):
        return "end"
    if state.get("pending_tool_calls"):
        return "tools"
    return "end"


def should_search_kb(state: AgentState) -> str:
    if state.get("query_policy_action") == "skip_kb":
        return "reason"
    if state.get("kb_queries"):
        return "kb_search"
    return "reason"
