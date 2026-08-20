"""Chat sub-agent graph — general dialogue with optional web_search tool."""
from __future__ import annotations

from functools import partial
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.harness.runtime.agent_loop import call_tools_node, reason_node, should_continue
from src.harness.prompts.system import SYSTEM_PROMPT_GENERAL
from src.harness.contracts.state import AgentState
from src.platform.llm.gateway import CostTracker
from src.harness.context.rag.policy import resolve_web_search_policy
from src.harness.tools.base import ToolRegistry, build_default_registry

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig

Emitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop_emit(_evt: dict[str, Any]) -> None:
    return None


def build_chat_graph(
    registry: ToolRegistry | None = None,
    emit: Emitter | None = None,
    *,
    llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    fallback_llm_cfg: "UserLLMConfig | None" = None,
):
    """General chat subgraph — web_search + time tools, no KB."""
    if registry is None:
        registry = build_default_registry(kb=None, llm_cfg=llm_cfg)

    cost = CostTracker()
    em = emit or _noop_emit
    web_search_policy = resolve_web_search_policy("general")

    g = StateGraph(AgentState)
    g.add_node(
        "reason",
        partial(
            reason_node,
            registry=registry,
            cost=cost,
            system_prompt=SYSTEM_PROMPT_GENERAL,
            excluded_tool_names=set(),
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
    g.set_entry_point("reason")
    g.add_conditional_edges("reason", should_continue, {"tools": "call_tools", "end": END})
    g.add_edge("call_tools", "reason")
    return g.compile(), cost
