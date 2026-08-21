"""Default single-agent ReAct graph for chat and knowledge-base answers.

``scope`` is a bounded capability-selection step, not a planner: it selects
only from ACL-filtered KB rows and never creates a task graph.  The same model
then runs one ``reason -> tools -> reason`` loop and chooses among the tools
that this scope permits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.capabilities.knowledge.application.routing import (
    AutoKBRoute,
    resolve_auto_kb_route_from_candidates,
)
from src.harness.context.rag.policy import resolve_web_search_policy
from src.harness.contracts.state import AgentState
from src.harness.prompts.system import SYSTEM_PROMPT_GENERAL, build_kb_system_prompt
from src.harness.runtime.agent_loop import call_tools_node, reason_node, should_continue
from src.harness.tools.base import ToolRegistry, build_default_registry
from src.platform.llm.gateway import CostTracker
from src.platform.observability import aspan

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import (
        UserEmbeddingConfig,
        UserLLMConfig,
        UserRerankerConfig,
    )

Emitter = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop_emit(_evt: dict[str, Any]) -> None:
    return None


def _build_multi_kb_registry(
    kbs: list[Any],
    *,
    kb_configs: dict[str, dict[str, Any]],
    llm_cfg: "UserLLMConfig | None",
    embedding_cfg: "UserEmbeddingConfig | None",
    reranker_cfg: "UserRerankerConfig | None",
    kb_web_search_enabled: bool,
) -> ToolRegistry:
    """Mount one bounded search capability across explicitly selected KBs."""
    from src.harness.tools.kb_search import KBSearchTool, MultiKBSearchTool
    from src.harness.tools.skill_report import make_kb_report_tool

    registry = ToolRegistry()
    tools = [
        KBSearchTool(
            kb,
            embedding_cfg=kb_configs.get(str(kb.id), {}).get("embedding_cfg", embedding_cfg),
            reranker_cfg=kb_configs.get(str(kb.id), {}).get("reranker_cfg", reranker_cfg),
        )
        for kb in kbs
    ]
    registry.register(MultiKBSearchTool(tools))
    registry.register(make_kb_report_tool(llm_cfg=llm_cfg))
    if kb_web_search_enabled:
        from src.harness.tools.web_search import WebSearchTool

        policy = resolve_web_search_policy("kb")
        registry.register(
            WebSearchTool(
                max_results_default=policy.results_per_call,
                max_results_cap=policy.results_per_call,
            )
        )
    return registry


@dataclass
class _ScopedTools:
    """Per-graph mutable cache; a graph is built once per chat run."""

    bound_kb: Any | None
    candidates: list[Any]
    llm_cfg: "UserLLMConfig | None"
    embedding_cfg: "UserEmbeddingConfig | None"
    reranker_cfg: "UserRerankerConfig | None"
    kb_web_search_enabled: bool
    configure_routed_kb: Callable[[Any], dict[str, Any]] | None
    selected_kbs: list[Any] = field(default_factory=list)
    route: AutoKBRoute | None = None
    registry: ToolRegistry | None = None

    async def resolve(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.bound_kb is not None:
            self.selected_kbs = [self.bound_kb]
            self.route = None
        elif self.candidates:
            self.route = await resolve_auto_kb_route_from_candidates(
                messages=messages,
                candidates=self.candidates,
                llm_cfg=self.llm_cfg,
            )
            self.selected_kbs = list(self.route.selected_kbs) if self.route.needs_retrieval else []
        else:
            self.selected_kbs = []
            self.route = None

        selected_ids = [str(kb.id) for kb in self.selected_kbs]
        route_metadata = self.route.trace_metadata() if self.route is not None else {
            "needs_retrieval": bool(self.selected_kbs),
            "selected_kb_id": selected_ids[0] if selected_ids else None,
            "selected_kb_ids": selected_ids,
            "source": "pinned" if self.bound_kb is not None else "none",
            "confidence": "high" if self.bound_kb is not None else "high",
            "reason": "pinned_kb" if self.bound_kb is not None else "no_kb_candidates",
            "latency_ms": 0,
            "candidate_count": len(self.candidates),
        }
        return {
            "kind": "knowledge_base" if self.selected_kbs else "general",
            "selected_kb_ids": selected_ids,
            "route": route_metadata,
        }

    def tools(self) -> ToolRegistry:
        if self.registry is not None:
            return self.registry
        if not self.selected_kbs:
            self.registry = build_default_registry(kb=None, llm_cfg=self.llm_cfg)
            return self.registry
        if len(self.selected_kbs) == 1:
            selected = self.selected_kbs[0]
            config = self.configure_routed_kb(selected) if self.configure_routed_kb else {}
            self.registry = build_default_registry(
                kb=selected,
                embedding_cfg=config.get("embedding_cfg", self.embedding_cfg),
                reranker_cfg=config.get("reranker_cfg", self.reranker_cfg),
                llm_cfg=self.llm_cfg,
                user_kb_web_search_enabled=bool(
                    config.get("kb_web_search_enabled", self.kb_web_search_enabled)
                ),
            )
            return self.registry
        configs = {
            str(kb.id): (self.configure_routed_kb(kb) if self.configure_routed_kb else {})
            for kb in self.selected_kbs
        }
        self.registry = _build_multi_kb_registry(
            self.selected_kbs,
            kb_configs=configs,
            llm_cfg=self.llm_cfg,
            embedding_cfg=self.embedding_cfg,
            reranker_cfg=self.reranker_cfg,
            kb_web_search_enabled=self.kb_web_search_enabled,
        )
        return self.registry

    def system_prompt(self) -> str:
        if not self.selected_kbs:
            return SYSTEM_PROMPT_GENERAL
        names = "、".join(str(kb.name) for kb in self.selected_kbs)
        descriptions = "\n".join(
            f"- {kb.name}: {kb.description or '(empty)'}" for kb in self.selected_kbs
        )
        return build_kb_system_prompt(
            names,
            descriptions,
            with_web_search=self.kb_web_search_enabled,
        )


def build_react_graph(
    emit: Emitter | None = None,
    *,
    kb: Any | None = None,
    kb_candidates: list[Any] | None = None,
    configure_routed_kb: Callable[[Any], dict[str, Any]] | None = None,
    llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    fallback_llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
    reranker_cfg: "UserRerankerConfig | None" = None,
    kb_web_search_enabled: bool = False,
    checkpointer=None,
):
    """Compile the product's default, constrained single-agent runtime."""
    em = emit or _noop_emit
    cost = CostTracker()
    scoped = _ScopedTools(
        bound_kb=kb,
        candidates=list(kb_candidates or []),
        llm_cfg=llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
        configure_routed_kb=configure_routed_kb,
    )

    async def scope_node(state: AgentState) -> AgentState:
        # Scope is a real ReAct graph stage.  Record it explicitly rather than
        # making a routed-KB span the only evidence that it ran.
        async with aspan("scope", metadata={"candidate_count": len(scoped.candidates)}) as obs:
            scope = await scoped.resolve(list(state.get("messages") or []))
            if obs is not None:
                obs.update(
                    metadata={
                        "kind": scope["kind"],
                        "selected_kb_ids": scope["selected_kb_ids"],
                        "route_source": scope["route"].get("source"),
                    }
                )
        route_cost = scoped.route.cost_usd if scoped.route is not None else 0.0
        # A stage summary is deliberately not model reasoning/chain-of-thought.
        # It only tells the UI which bounded capability scope was selected.
        route = scope["route"]
        await em(
            {
                "event": "agent_route",
                "agent": "react",
                "scope": scope["kind"],
                "source": str(route.get("source") or "none"),
                "confidence": str(route.get("confidence") or "high"),
                "reason": str(route.get("reason") or "capability_scope_selected"),
            }
        )
        if scoped.route is not None and scoped.selected_kbs:
            await em(
                {
                    "event": "kb_routed",
                    "scope": "turn",
                    "agent": "react",
                    "kb_id": scoped.selected_kbs[0].id,
                    "kb_ids": [item.id for item in scoped.selected_kbs],
                    "name": "、".join(str(item.name) for item in scoped.selected_kbs),
                    "source": scoped.route.source,
                    "confidence": scoped.route.confidence,
                }
            )
        return {
            **state,
            "runtime_scope": scope,
            "kb_id": scope["selected_kb_ids"][0] if scope["selected_kb_ids"] else None,
            # Keep the persisted trace and observability payload compatible
            # with the previous Supervisor-owned auto-route contract.
            "kb_auto_route": scope["route"] if scoped.route is not None else state.get("kb_auto_route"),
            "cost_usd": route_cost,
        }

    async def reason(state: AgentState) -> AgentState:
        result = await reason_node(
            state,
            registry=scoped.tools(),
            cost=cost,
            system_prompt=scoped.system_prompt(),
            excluded_tool_names=set(),
            llm_cfg=llm_cfg,
            complex_llm_cfg=complex_llm_cfg,
            fallback_llm_cfg=fallback_llm_cfg,
            emit=em,
        )
        route_cost = scoped.route.cost_usd if scoped.route is not None else 0.0
        model_cost = result.get("cost_usd")
        result["cost_usd"] = (
            None if route_cost is None or model_cost is None else float(route_cost) + float(model_cost)
        )
        return result

    async def call_tools(state: AgentState) -> AgentState:
        policy = resolve_web_search_policy(
            "kb" if scoped.selected_kbs and scoped.kb_web_search_enabled else "general"
        )
        return await call_tools_node(
            state,
            registry=scoped.tools(),
            emit=em,
            llm_cfg=llm_cfg,
            web_search_max_calls=policy.max_calls,
            web_search_evidence_limit=policy.evidence_limit,
        )

    graph = StateGraph(AgentState)
    graph.add_node("scope", scope_node)
    graph.add_node("reason", reason)
    graph.add_node("call_tools", call_tools)
    graph.set_entry_point("scope")
    graph.add_edge("scope", "reason")
    graph.add_conditional_edges("reason", should_continue, {"tools": "call_tools", "end": END})
    graph.add_edge("call_tools", "reason")
    return graph.compile(checkpointer=checkpointer), cost
