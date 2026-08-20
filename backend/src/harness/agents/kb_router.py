"""The bounded KB-selection sub-agent used by the supervisor DAG."""
from __future__ import annotations

from typing import Any

from src.harness.orchestration.registry import Emitter, RuntimeDeps
from src.platform.llm import CostTracker
from src.capabilities.knowledge.application.routing import resolve_auto_kb_route_from_candidates


class _KBRouterGraph:
    def __init__(self, deps: RuntimeDeps) -> None:
        self._deps = deps

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        decision = await resolve_auto_kb_route_from_candidates(
            messages=list(state.get("messages") or []),
            candidates=list(self._deps.kb_candidates),
            llm_cfg=self._deps.llm_cfg,
        )
        return {
            **state,
            "kb_route_decision": decision,
            # Deterministic routing has no billable model call. Preserve None
            # only for an LLM call whose price is genuinely unknown.
            "cost_usd": decision.cost_usd if decision.source == "llm" else 0.0,
        }


def build_kb_router_graph(
    deps: RuntimeDeps, *, emit: Emitter | None = None
) -> tuple[Any, CostTracker]:
    """Return a graph-compatible, no-side-effect selection capability."""
    _ = emit
    return _KBRouterGraph(deps), CostTracker()
