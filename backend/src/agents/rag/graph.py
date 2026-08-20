"""RAG sub-agent graph — query_policy → kb_search → reason ⇄ tools."""
from __future__ import annotations

from functools import partial
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.runtime.agent_loop import (
    call_tools_node,
    kb_search_node,
    query_policy_node,
    reason_node,
    should_continue,
    should_search_kb,
)
from src.prompts.system import build_kb_reason_system_prompt
from src.harness.contracts.state import AgentState
from src.models.gateway import CostTracker
from src.context.rag.policy import resolve_web_search_policy
from src.tools.base import ToolRegistry, build_default_registry

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserEmbeddingConfig, UserLLMConfig, UserRerankerConfig

Emitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop_emit(_evt: dict[str, Any]) -> None:
    return None


def build_rag_graph(
    registry: ToolRegistry | None = None,
    emit: Emitter | None = None,
    *,
    kb,
    llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    triage_llm_cfg: "UserLLMConfig | None" = None,
    fallback_llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
    reranker_cfg: "UserRerankerConfig | None" = None,
    kb_web_search_enabled: bool = False,
):
    """KB-bound subgraph — query_policy → kb_search → reason ⇄ tools."""
    if kb is None:
        raise ValueError("build_rag_graph requires kb")

    if registry is None:
        registry = build_default_registry(
            kb=kb,
            embedding_cfg=embedding_cfg,
            reranker_cfg=reranker_cfg,
            llm_cfg=llm_cfg,
            user_kb_web_search_enabled=kb_web_search_enabled,
        )

    system_prompt = build_kb_reason_system_prompt(
        kb.name,
        kb.description or "",
        with_web_search=kb_web_search_enabled,
    )
    web_search_policy = resolve_web_search_policy(
        "kb" if kb_web_search_enabled else "disabled"
    )
    cost = CostTracker()
    em = emit or _noop_emit

    g = StateGraph(AgentState)
    g.add_node(
        "query_policy",
        partial(
            query_policy_node,
            cost=cost,
            kb_name=kb.name,
            kb_description=kb.description or "",
            llm_cfg=triage_llm_cfg or llm_cfg,
        ),
    )
    g.add_node(
        "kb_search",
        partial(kb_search_node, registry=registry, emit=em),
    )
    g.add_node(
        "reason",
        partial(
            reason_node,
            registry=registry,
            cost=cost,
            system_prompt=system_prompt,
            excluded_tool_names={"search_kb", "search_kg"},
            llm_cfg=llm_cfg,
            complex_llm_cfg=complex_llm_cfg,
            fallback_llm_cfg=fallback_llm_cfg,
            emit=em,
        ),
    )
    g.add_node(
        "call_tools",
        partial(
            call_tools_node,
            registry=registry,
            emit=em,
            llm_cfg=llm_cfg,
            web_search_max_calls=web_search_policy.max_calls,
            web_search_evidence_limit=web_search_policy.evidence_limit,
        ),
    )
    g.set_entry_point("query_policy")
    g.add_conditional_edges(
        "query_policy",
        should_search_kb,
        {"kb_search": "kb_search", "reason": "reason"},
    )
    g.add_edge("kb_search", "reason")
    g.add_conditional_edges("reason", should_continue, {"tools": "call_tools", "end": END})
    g.add_edge("call_tools", "reason")
    return g.compile(), cost
