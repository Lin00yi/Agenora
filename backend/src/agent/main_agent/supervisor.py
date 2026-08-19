"""Supervisor runtime — plans a task DAG and dispatches bound sub-agents.

Routing uses a three-layer cascade (rule → triage → complex). Optional
rag→chat follow-up when retrieval is empty and chat was not already planned.
web_search stays a chat tool.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph

from src.agent.main_agent.dag import TaskDag, append_chat_followup
from src.agent.main_agent.router import resolve_agent_route
from src.agent.main_agent.validate import ready_tasks, validate_and_bind
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
    kb_id: str | None
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
    task_dag: TaskDag
    task_status: dict[str, str]
    active_task_id: str | None


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


def _has_chat_task(dag: TaskDag | None) -> bool:
    for task in (dag or {}).get("tasks") or []:
        if task.get("type") == "qa_chat" or task.get("agent") == "chat":
            return True
    return False


def should_handoff_to_chat(
    state: SupervisorState,
    *,
    allow_rag_chat_handoff: bool,
    registry: AgentRegistry,
) -> tuple[bool, str]:
    """Allow one rag→chat follow-up when retrieval produced no evidence."""
    if not allow_rag_chat_handoff:
        return False, "handoff_disabled"
    if int(state.get("handoff_count") or 0) >= 1:
        return False, "handoff_budget_exhausted"
    if state.get("last_agent") != "rag":
        return False, "not_rag"
    if _has_chat_task(state.get("task_dag")):
        return False, "chat_already_planned"
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
    out.setdefault("messages", list(state.get("messages") or []))
    out["iterations"] = 0
    out.setdefault("tool_call_log", [])
    out.setdefault("citations", [])
    return out


def _dag_event_tasks(dag: TaskDag) -> list[dict[str, Any]]:
    return [
        {
            "id": t.get("id"),
            "type": t.get("type"),
            "agent": t.get("agent"),
            "depends_on": t.get("depends_on") or [],
        }
        for t in dag.get("tasks") or []
    ]


def _dag_ready_event(dag: TaskDag) -> dict[str, Any]:
    return {
        "event": "dag_ready",
        "reason": dag.get("reason") or "planned",
        "source": dag.get("source") or "fallback",
        "confidence": dag.get("confidence") or "medium",
        "tasks": _dag_event_tasks(dag),
    }


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
            getattr(settings, "agent_allow_rag_chat_handoff", True)
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
        dag: TaskDag = {
            "tasks": list(decision.get("tasks") or []),
            "reason": decision["reason"],
            "source": decision["source"],
            "confidence": decision["confidence"],
            "latency_ms": decision["latency_ms"],
        }
        status = {str(t.get("id")): "pending" for t in dag.get("tasks") or [] if t.get("id")}
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
                "tasks": [
                    {"id": t.get("id"), "type": t.get("type"), "agent": t.get("agent")}
                    for t in dag.get("tasks") or []
                ],
            }
        )
        await em(_dag_ready_event(dag))
        base_messages = list(state.get("base_messages") or state.get("messages") or [])
        return {
            **state,
            "base_messages": base_messages,
            "task_dag": dag,
            "task_status": status,
            "active_task_id": None,
            "active_agent": None,
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

    @traced("supervisor_schedule")
    async def schedule_node(state: SupervisorState) -> SupervisorState:
        dag = state.get("task_dag") or {"tasks": []}
        status = dict(state.get("task_status") or {})
        ready = ready_tasks(dag, status)
        if not ready:
            return {
                **state,
                "supervisor_decision": "finish",
                "active_task_id": None,
                "active_agent": None,
            }

        task = ready[0]
        task_id = str(task.get("id") or "")
        agent_id = str(task.get("agent") or "")
        spec = reg.get(agent_id) if agent_id else None
        if spec is not None and spec.requires_kb and runtime.kb is None:
            agent_id = "chat"
            await em(
                {
                    "event": "agent_route",
                    "agent": agent_id,
                    "reason": "rag_missing_kb_fallback",
                }
            )

        last = state.get("last_agent")
        switching = bool(last) and last != agent_id
        if switching:
            await em(
                {
                    "event": "agent_route",
                    "agent": agent_id,
                    "reason": state.get("route_reason") or "next_task",
                    "task_id": task_id,
                    "source": state.get("route_source") or "rule",
                }
            )

        trace = list(state.get("supervisor_trace") or [])
        trace.append(
            {
                "event": "schedule",
                "task_id": task_id,
                "agent": agent_id,
                "type": task.get("type"),
            }
        )
        updates: SupervisorState = {
            **state,
            "active_task_id": task_id,
            "active_agent": agent_id,
            "supervisor_decision": "dispatch",
            "supervisor_trace": trace,
            "task_status": status,
        }
        if switching:
            seed = list(state.get("base_messages") or state.get("messages") or [])
            updates["messages"] = seed
            updates["report_streamed"] = False
            updates["final_report"] = None
            updates["retrieved_evidence"] = []
            updates["kb_context"] = ""
            updates["kb_queries"] = []
            updates["kb_search_done"] = False
            updates["pending_tool_calls"] = []  # type: ignore[typeddict-unknown-key]
        return updates

    @traced("supervisor_dispatch")
    async def dispatch_node(state: SupervisorState) -> SupervisorState:
        agent_id = state.get("active_agent")
        task_id = state.get("active_task_id")
        if not agent_id:
            raise RuntimeError("supervisor dispatch without active_agent")

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
        result_payload = {
            "final_report": sub_out.get("final_report"),
            "citations": list(sub_out.get("citations") or []),
            "retrieved_evidence_count": len(sub_out.get("retrieved_evidence") or []),
            "query_policy_action": sub_out.get("query_policy_action"),
            "cost_usd": sub_out.get("cost_usd"),
        }
        results[agent_id] = result_payload
        if task_id:
            results[task_id] = result_payload

        status = dict(state.get("task_status") or {})
        if task_id:
            status[task_id] = "done"

        trace = list(state.get("supervisor_trace") or [])
        trace.append(
            {
                "event": "completed",
                "agent": agent_id,
                "task_id": task_id,
                "evidence": result_payload["retrieved_evidence_count"],
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
            "task_status": status,
        }

    @traced("supervisor_review")
    async def review_node(state: SupervisorState) -> SupervisorState:
        do_handoff, reason = should_handoff_to_chat(
            state,
            allow_rag_chat_handoff=allow_rag_chat_handoff,
            registry=reg,
        )
        trace = list(state.get("supervisor_trace") or [])
        dag = state.get("task_dag") or {"tasks": []}
        status = dict(state.get("task_status") or {})
        has_kb = runtime.kb is not None or bool(state.get("kb_id"))

        if do_handoff:
            extended = append_chat_followup(dag, reason=reason)
            bound = validate_and_bind(extended, registry=reg, has_kb=has_kb)
            for task in bound.get("tasks") or []:
                tid = str(task.get("id") or "")
                status.setdefault(tid, "pending")
            await em(
                {
                    "event": "agent_handoff",
                    "from": state.get("last_agent"),
                    "to": "chat",
                    "reason": reason,
                }
            )
            await em(_dag_ready_event(bound))
            trace.append(
                {
                    "event": "handoff",
                    "from": state.get("last_agent"),
                    "to": "chat",
                    "reason": reason,
                }
            )
            return {
                **state,
                "task_dag": bound,
                "task_status": status,
                "handoff_count": int(state.get("handoff_count") or 0) + 1,
                "route_reason": reason,
                "supervisor_decision": "dispatch",
                "supervisor_trace": trace,
            }

        if ready_tasks(dag, status):
            trace.append({"event": "continue", "reason": "pending_tasks"})
            return {
                **state,
                "supervisor_decision": "dispatch",
                "supervisor_trace": trace,
            }

        trace.append({"event": "finish", "agent": state.get("last_agent"), "reason": reason})
        return {
            **state,
            "supervisor_decision": "finish",
            "supervisor_trace": trace,
        }

    def after_route(_state: SupervisorState) -> str:
        return "schedule"

    def after_schedule(state: SupervisorState) -> str:
        if state.get("supervisor_decision") == "dispatch" and state.get("active_agent"):
            return "dispatch"
        return "end"

    def after_dispatch(_state: SupervisorState) -> str:
        return "review"

    def after_review(state: SupervisorState) -> str:
        if state.get("supervisor_decision") == "dispatch":
            return "schedule"
        return "end"

    g = StateGraph(SupervisorState)
    g.add_node("route", route_node)
    g.add_node("schedule", schedule_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("review", review_node)
    g.set_entry_point("route")
    g.add_conditional_edges("route", after_route, {"schedule": "schedule"})
    g.add_conditional_edges(
        "schedule",
        after_schedule,
        {"dispatch": "dispatch", "end": END},
    )
    g.add_conditional_edges("dispatch", after_dispatch, {"review": "review"})
    g.add_conditional_edges(
        "review",
        after_review,
        {"schedule": "schedule", "end": END},
    )
    return g.compile(), parent_cost
