"""Supervisor runtime — routes among pluggable sub-agents.

Routing uses a three-layer cascade (rule → triage → complex). Optional
rag→chat handoff when retrieval is empty. web_search stays a chat tool.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph

from src.agent.main_agent.router import resolve_agent_route
from src.agent.registry import AgentRegistry, RuntimeDeps, build_default_agent_registry
from src.infra.llm import CostTracker
from src.observability import traced

Emitter = Callable[[dict[str, Any]], Awaitable[None]]

SupervisorDecision = Literal["dispatch", "finish"]

# Keys copied into each subgraph invoke (AgentState-compatible).
_SUBGRAPH_INPUT_KEYS = (
    "messages",
    "iterations",
    "tool_call_log",
    "citations",
    "prompt_injection_risk",
    "prompt_injection_reasons",
    "rag_suspicious_chunks",
    "rag_filtered_chunks",
    "web_search_call_count",
    "web_search_evidence_count",
    "retrieved_evidence",
    "kb_context",
    "kb_queries",
    "kb_search_done",
)


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
    # Supervisor control plane
    kb_id: str | None
    # Conversation seed before any subgraph mutates the tool loop.
    base_messages: list[dict[str, Any]]
    active_agent: str | None
    last_agent: str | None
    agent_results: dict[str, Any]
    route_reason: str
    route_source: str
    route_confidence: str
    handoff_count: int
    supervisor_trace: list[dict[str, Any]]
    supervisor_decision: SupervisorDecision


def _latest_user_text(messages: list[dict[str, Any]] | None) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "\n".join(
                str(block.get("text", "")).strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""


def should_handoff_to_chat(
    state: SupervisorState,
    *,
    allow_rag_chat_handoff: bool,
    registry: AgentRegistry,
) -> tuple[bool, str]:
    """Allow one rag→chat handoff when retrieval produced no evidence."""
    if not allow_rag_chat_handoff:
        return False, "handoff_disabled"
    if int(state.get("handoff_count") or 0) >= 1:
        return False, "handoff_budget_exhausted"
    if state.get("last_agent") != "rag":
        return False, "not_rag"
    if "chat" not in registry.available(has_kb=False):
        return False, "chat_unavailable"
    spec = registry.get("rag")
    if "chat" not in spec.handoff_targets:
        return False, "handoff_not_declared"
    if state.get("query_policy_action") == "skip_kb":
        return False, "skip_kb"
    evidence = state.get("retrieved_evidence") or []
    if evidence:
        return False, "has_evidence"
    return True, "rag_empty_evidence"


def _merge_cost(left: float | None, right: float | None) -> float | None:
    """Sum only when both sides have a known price; else unknown."""
    if left is None or right is None:
        return None
    return float(left) + float(right)


def _subgraph_input(state: SupervisorState) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _SUBGRAPH_INPUT_KEYS:
        if key in state:
            out[key] = state[key]
    # Fresh loop counters per agent instance.
    out.setdefault("messages", list(state.get("messages") or []))
    out["iterations"] = 0
    out.setdefault("tool_call_log", [])
    out.setdefault("citations", [])
    return out


def _merge_tool_logs(*groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in groups:
        if not group:
            continue
        merged.extend(list(group))
    return merged


def build_supervisor_graph(
    *,
    emit: Emitter | None = None,
    registry: AgentRegistry | None = None,
    deps: RuntimeDeps | None = None,
    allow_rag_chat_handoff: bool | None = None,
    kb=None,
    llm_cfg=None,
    complex_llm_cfg=None,
    triage_llm_cfg=None,
    fallback_llm_cfg=None,
    embedding_cfg=None,
    reranker_cfg: Any | None = None,
    kb_web_search_enabled: bool = False,
):
    """Compile the multi-agent supervisor around a pluggable registry."""
    from src.settings import get_settings

    async def _noop_emit(_evt: dict[str, Any]) -> None:
        return None

    em = emit or _noop_emit
    reg = registry or build_default_agent_registry()
    runtime = deps or RuntimeDeps(
        emit=em,
        kb=kb,
        llm_cfg=llm_cfg,
        complex_llm_cfg=complex_llm_cfg,
        triage_llm_cfg=triage_llm_cfg,
        fallback_llm_cfg=fallback_llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
    )
    if deps is None:
        runtime.emit = em
        runtime.kb = kb if kb is not None else runtime.kb

    settings = get_settings()
    if allow_rag_chat_handoff is None:
        allow_rag_chat_handoff = bool(
            getattr(settings, "agent_allow_rag_chat_handoff", False)
        )

    parent_cost = CostTracker()

    @traced("supervisor_route")
    async def route_node(state: SupervisorState) -> SupervisorState:
        has_kb = runtime.kb is not None or bool(state.get("kb_id"))
        user_query = _latest_user_text(state.get("messages") or state.get("base_messages"))
        decision = await resolve_agent_route(
            has_kb=has_kb,
            registry=reg,
            user_query=user_query,
            cost=parent_cost,
            triage_llm_cfg=runtime.triage_llm_cfg,
            complex_llm_cfg=runtime.complex_llm_cfg,
            default_llm_cfg=runtime.llm_cfg,
            mode=getattr(settings, "agent_route_mode", "layered"),
        )
        agent_id = decision["target"]
        reason = decision["reason"]
        trace = list(state.get("supervisor_trace") or [])
        trace.append(
            {
                "event": "route",
                "agent": agent_id,
                "reason": reason,
                "source": decision["source"],
                "confidence": decision["confidence"],
                "latency_ms": decision["latency_ms"],
            }
        )
        await em(
            {
                "event": "agent_route",
                "agent": agent_id,
                "reason": reason,
                "source": decision["source"],
                "confidence": decision["confidence"],
            }
        )
        base_messages = list(state.get("base_messages") or state.get("messages") or [])
        return {
            **state,
            "base_messages": base_messages,
            "active_agent": agent_id,
            "route_reason": reason,
            "route_source": decision["source"],
            "route_confidence": decision["confidence"],
            "supervisor_decision": "dispatch",
            "supervisor_trace": trace,
            "agent_results": dict(state.get("agent_results") or {}),
            "handoff_count": int(state.get("handoff_count") or 0),
            "kb_id": state.get("kb_id")
            or (getattr(runtime.kb, "id", None) if runtime.kb else None),
            "cost_usd": (
                parent_cost.total_usd if parent_cost.calls else state.get("cost_usd")
            ),
        }


    @traced("supervisor_dispatch")
    async def dispatch_node(state: SupervisorState) -> SupervisorState:
        agent_id = state.get("active_agent")
        if not agent_id:
            raise RuntimeError("supervisor dispatch without active_agent")
        spec = reg.get(agent_id)
        if spec.requires_kb and runtime.kb is None:
            # Soft fallback keeps the turn alive if registry/route drifted.
            agent_id = "chat"
            spec = reg.get(agent_id)
            await em(
                {
                    "event": "agent_route",
                    "agent": agent_id,
                    "reason": "rag_missing_kb_fallback",
                }
            )

        async def tagged_emit(evt: dict[str, Any]) -> None:
            await em({**evt, "agent": agent_id})

        builder = reg.builder(agent_id)
        graph, _cost = builder(runtime, emit=tagged_emit)
        sub_in = _subgraph_input(state)
        sub_out = await graph.ainvoke(sub_in)

        prev_cost = state.get("cost_usd")
        sub_cost = sub_out.get("cost_usd")
        already_ran = state.get("last_agent") is not None or int(
            state.get("handoff_count") or 0
        ) > 0
        next_cost = _merge_cost(prev_cost, sub_cost) if already_ran else sub_cost

        results = dict(state.get("agent_results") or {})
        results[agent_id] = {
            "final_report": sub_out.get("final_report"),
            "citations": list(sub_out.get("citations") or []),
            "retrieved_evidence_count": len(sub_out.get("retrieved_evidence") or []),
            "query_policy_action": sub_out.get("query_policy_action"),
            "cost_usd": sub_out.get("cost_usd"),
        }
        trace = list(state.get("supervisor_trace") or [])
        trace.append(
            {
                "event": "completed",
                "agent": agent_id,
                "evidence": results[agent_id]["retrieved_evidence_count"],
            }
        )

        merged_citations = list(state.get("citations") or [])
        for item in sub_out.get("citations") or []:
            if item not in merged_citations:
                merged_citations.append(item)

        return {
            **state,
            "messages": list(sub_out.get("messages") or state.get("messages") or []),
            "final_report": sub_out.get("final_report"),
            "report_streamed": bool(sub_out.get("report_streamed")),
            "citations": merged_citations,
            "prompt_trace": sub_out.get("prompt_trace") or state.get("prompt_trace"),
            "cost_usd": next_cost,
            "retrieved_evidence": list(sub_out.get("retrieved_evidence") or []),
            "kb_context": sub_out.get("kb_context") or state.get("kb_context"),
            "kb_queries": list(sub_out.get("kb_queries") or []),
            "kb_search_done": bool(sub_out.get("kb_search_done")),
            "query_policy_action": sub_out.get("query_policy_action")
            or state.get("query_policy_action"),
            "query_policy_reason": sub_out.get("query_policy_reason")
            or state.get("query_policy_reason"),
            "query_policy_source": sub_out.get("query_policy_source")
            or state.get("query_policy_source"),
            "query_policy_latency_ms": int(
                sub_out.get("query_policy_latency_ms")
                or state.get("query_policy_latency_ms")
                or 0
            ),
            "prompt_injection_risk": sub_out.get("prompt_injection_risk")
            or state.get("prompt_injection_risk"),
            "prompt_injection_reasons": list(
                sub_out.get("prompt_injection_reasons")
                or state.get("prompt_injection_reasons")
                or []
            ),
            "rag_suspicious_chunks": int(
                sub_out.get("rag_suspicious_chunks")
                or state.get("rag_suspicious_chunks")
                or 0
            ),
            "rag_filtered_chunks": list(
                sub_out.get("rag_filtered_chunks")
                or state.get("rag_filtered_chunks")
                or []
            ),
            "tool_call_log": _merge_tool_logs(
                state.get("tool_call_log"),
                sub_out.get("tool_call_log"),
            ),
            "web_search_call_count": int(sub_out.get("web_search_call_count") or 0),
            "web_search_evidence_count": int(sub_out.get("web_search_evidence_count") or 0),
            "last_agent": agent_id,
            "active_agent": agent_id,
            "agent_results": results,
            "supervisor_trace": trace,
        }

    @traced("supervisor_review")
    async def review_node(state: SupervisorState) -> SupervisorState:
        do_handoff, reason = should_handoff_to_chat(
            state,
            allow_rag_chat_handoff=allow_rag_chat_handoff,
            registry=reg,
        )
        trace = list(state.get("supervisor_trace") or [])
        if do_handoff:
            await em(
                {
                    "event": "agent_handoff",
                    "from": state.get("last_agent"),
                    "to": "chat",
                    "reason": reason,
                }
            )
            trace.append(
                {
                    "event": "handoff",
                    "from": state.get("last_agent"),
                    "to": "chat",
                    "reason": reason,
                }
            )
            seed = list(state.get("base_messages") or state.get("messages") or [])
            return {
                **state,
                "active_agent": "chat",
                "handoff_count": int(state.get("handoff_count") or 0) + 1,
                "route_reason": reason,
                "supervisor_decision": "dispatch",
                "supervisor_trace": trace,
                # Fresh chat instance from the original turn; keep prior citations.
                "messages": seed,
                "report_streamed": False,
                "final_report": None,
                "retrieved_evidence": [],
                "kb_context": "",
                "kb_queries": [],
                "kb_search_done": False,
                "pending_tool_calls": [],
            }

        trace.append({"event": "finish", "agent": state.get("last_agent"), "reason": reason})
        return {
            **state,
            "supervisor_decision": "finish",
            "supervisor_trace": trace,
        }

    def after_route(state: SupervisorState) -> str:
        return "dispatch"

    def after_dispatch(state: SupervisorState) -> str:
        return "review"

    def after_review(state: SupervisorState) -> str:
        if state.get("supervisor_decision") == "dispatch":
            return "dispatch"
        return "end"

    g = StateGraph(SupervisorState)
    g.add_node("route", route_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("review", review_node)
    g.set_entry_point("route")
    g.add_conditional_edges("route", after_route, {"dispatch": "dispatch"})
    g.add_conditional_edges("dispatch", after_dispatch, {"review": "review"})
    g.add_conditional_edges(
        "review",
        after_review,
        {"dispatch": "dispatch", "end": END},
    )
    return g.compile(), parent_cost
