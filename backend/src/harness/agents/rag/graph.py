"""RAG sub-agent graph — query_policy → kb_search → reason ⇄ tools."""
from __future__ import annotations

from functools import partial
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.harness.runtime.agent_loop import (
    call_tools_node,
    kb_search_node,
    query_policy_node,
    reason_node,
    should_continue,
    should_search_kb,
)
from src.harness.prompts.system import build_kb_reason_system_prompt
from src.harness.contracts.state import AgentState
from src.platform.llm.gateway import CostTracker
from src.harness.context.rag.policy import resolve_web_search_policy
from src.harness.tools.base import ToolRegistry, build_default_registry

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
    kbs: list[Any] | None = None,
    kb_configs: dict[str, dict[str, Any]] | None = None,
    llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    triage_llm_cfg: "UserLLMConfig | None" = None,
    fallback_llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
    reranker_cfg: "UserRerankerConfig | None" = None,
    kb_web_search_enabled: bool = False,
):
    """KB-bound subgraph — one or more ACL-scoped KBs, then one answer."""
    selected_kbs = list(kbs or ([kb] if kb is not None else []))
    if not selected_kbs:
        raise ValueError("build_rag_graph requires kb")

    if registry is None:
        if len(selected_kbs) == 1:
            registry = build_default_registry(
                kb=selected_kbs[0],
                embedding_cfg=embedding_cfg,
                reranker_cfg=reranker_cfg,
                llm_cfg=llm_cfg,
                user_kb_web_search_enabled=kb_web_search_enabled,
            )
        else:
            from src.harness.tools.base import ToolRegistry
            from src.harness.tools.kb_search import KBSearchTool, MultiKBSearchTool
            from src.harness.tools.web_search import WebSearchTool

            configs = kb_configs or {}
            tools = []
            for item in selected_kbs:
                config = configs.get(str(item.id), {})
                tools.append(
                    KBSearchTool(
                        item,
                        embedding_cfg=config.get("embedding_cfg", embedding_cfg),
                        reranker_cfg=config.get("reranker_cfg", reranker_cfg),
                    )
                )
            registry = ToolRegistry()
            registry.register(MultiKBSearchTool(tools))
            if kb_web_search_enabled:
                policy = resolve_web_search_policy("kb")
                registry.register(
                    WebSearchTool(
                        max_results_default=policy.results_per_call,
                        max_results_cap=policy.results_per_call,
                    )
                )

    kb_names = "、".join(str(item.name) for item in selected_kbs)
    kb_descriptions = "\n".join(
        f"- {item.name}: {item.description or '(empty)'}" for item in selected_kbs
    )
    system_prompt = build_kb_reason_system_prompt(
        kb_names,
        kb_descriptions,
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
            kb_name=kb_names,
            kb_description=kb_descriptions,
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
