"""Pluggable agent capability registry.

Templates are registered once; the supervisor instantiates a subgraph per task.
``web_search`` stays a tool inside ``chat`` — it is not an agent entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, TYPE_CHECKING

from src.infra.llm import CostTracker

if TYPE_CHECKING:
    from src.settings_user import UserEmbeddingConfig, UserLLMConfig, UserRerankerConfig

Emitter = Callable[[dict[str, Any]], Awaitable[None]]
SideEffect = Literal["none", "read", "write"]
GraphBuilder = Callable[..., tuple[Any, CostTracker]]


@dataclass(frozen=True)
class AgentSpec:
    """Capability template — not a live conversation persona."""

    id: str
    description: str
    side_effect: SideEffect = "none"
    requires_kb: bool = False
    accept_handoff: bool = True
    # Closed set of agents this capability may hand off to after it runs.
    handoff_targets: tuple[str, ...] = ()


@dataclass
class RuntimeDeps:
    """Per-request wiring shared by every agent factory."""

    emit: Emitter
    kb: Any | None = None
    llm_cfg: "UserLLMConfig | None" = None
    complex_llm_cfg: "UserLLMConfig | None" = None
    triage_llm_cfg: "UserLLMConfig | None" = None
    fallback_llm_cfg: "UserLLMConfig | None" = None
    embedding_cfg: "UserEmbeddingConfig | None" = None
    reranker_cfg: "UserRerankerConfig | None" = None
    kb_web_search_enabled: bool = False


@dataclass
class AgentRegistry:
    """Closed catalog of schedulable agents."""

    _specs: dict[str, AgentSpec] = field(default_factory=dict)
    _builders: dict[str, GraphBuilder] = field(default_factory=dict)

    def register(self, spec: AgentSpec, builder: GraphBuilder) -> None:
        if not spec.id or not spec.id.strip():
            raise ValueError("agent id must be non-empty")
        if spec.id in self._specs:
            raise ValueError(f"agent already registered: {spec.id}")
        self._specs[spec.id] = spec
        self._builders[spec.id] = builder

    def get(self, agent_id: str) -> AgentSpec:
        try:
            return self._specs[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def builder(self, agent_id: str) -> GraphBuilder:
        try:
            return self._builders[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def ids(self) -> list[str]:
        return list(self._specs.keys())

    def available(self, *, has_kb: bool) -> list[str]:
        out: list[str] = []
        for agent_id, spec in self._specs.items():
            if spec.requires_kb and not has_kb:
                continue
            out.append(agent_id)
        return out


def build_default_agent_registry() -> AgentRegistry:
    """Register built-in chat + rag templates.

    Additional action agents register the same way without changing the supervisor.
    """
    from src.agent.sub_agents.chat_agent import build_chat_graph
    from src.agent.sub_agents.rag_agent import build_rag_graph

    registry = AgentRegistry()

    def _build_chat(deps: RuntimeDeps, *, emit: Emitter | None = None) -> tuple[Any, CostTracker]:
        return build_chat_graph(
            emit=emit or deps.emit,
            llm_cfg=deps.llm_cfg,
            complex_llm_cfg=deps.complex_llm_cfg,
            fallback_llm_cfg=deps.fallback_llm_cfg,
        )

    def _build_rag(deps: RuntimeDeps, *, emit: Emitter | None = None) -> tuple[Any, CostTracker]:
        if deps.kb is None:
            raise ValueError("rag agent requires kb")
        return build_rag_graph(
            kb=deps.kb,
            emit=emit or deps.emit,
            llm_cfg=deps.llm_cfg,
            complex_llm_cfg=deps.complex_llm_cfg,
            triage_llm_cfg=deps.triage_llm_cfg,
            fallback_llm_cfg=deps.fallback_llm_cfg,
            embedding_cfg=deps.embedding_cfg,
            reranker_cfg=deps.reranker_cfg,
            kb_web_search_enabled=deps.kb_web_search_enabled,
        )

    registry.register(
        AgentSpec(
            id="chat",
            description="General chat; may call web_search / time tools",
            side_effect="none",
            requires_kb=False,
            handoff_targets=(),
        ),
        _build_chat,
    )
    registry.register(
        AgentSpec(
            id="rag",
            description="Private KB retrieval and grounded answers",
            side_effect="read",
            requires_kb=True,
            # Hybrid: empty / weak retrieval can continue as general chat (+ web tool).
            handoff_targets=("chat",),
        ),
        _build_rag,
    )
    return registry
