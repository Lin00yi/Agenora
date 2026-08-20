"""Schedulable capability registry owned by the execution harness."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, TYPE_CHECKING

from src.harness.contracts.events import EventEmitter
from src.harness.contracts.runtime import RunContext
from src.adapters.llm import CostTracker

if TYPE_CHECKING:
    from src.settings_user import UserEmbeddingConfig, UserLLMConfig, UserRerankerConfig

Emitter = EventEmitter
SideEffect = Literal["none", "read", "write"]
GraphBuilder = Callable[..., tuple[Any, CostTracker]]


@dataclass(frozen=True)
class AgentSpec:
    """A schedulable capability template, not a user-facing persona."""

    id: str
    description: str
    side_effect: SideEffect = "none"
    requires_kb: bool = False
    accept_handoff: bool = True
    handoff_targets: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()


@dataclass
class RuntimeDeps:
    """Per-run dependencies provided by bootstrap/application services."""

    emit: Emitter
    run: RunContext | None = None
    kb: Any | None = None
    llm_cfg: "UserLLMConfig | None" = None
    complex_llm_cfg: "UserLLMConfig | None" = None
    triage_llm_cfg: "UserLLMConfig | None" = None
    fallback_llm_cfg: "UserLLMConfig | None" = None
    embedding_cfg: "UserEmbeddingConfig | None" = None
    reranker_cfg: "UserRerankerConfig | None" = None
    kb_web_search_enabled: bool = False
    kb_candidates: list[Any] = field(default_factory=list)
    configure_routed_kb: Callable[[Any], Any] | None = None
    on_kb_routed: Callable[[Any, Any], Awaitable[None]] | None = None


@dataclass
class AgentRegistry:
    """Closed catalog of harness capabilities eligible for scheduling."""

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
        return [
            agent_id
            for agent_id, spec in self._specs.items()
            if has_kb or not spec.requires_kb
        ]


def build_default_agent_registry() -> AgentRegistry:
    """Register the built-in chat, retrieval, and KB-routing capabilities."""
    from src.agents.chat import build_chat_graph
    from src.agents.kb_router import build_kb_router_graph
    from src.agents.rag import build_rag_graph

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
            id="kb_router",
            description="Select one ACL-scoped KB for an unbound turn",
            side_effect="none",
            requires_kb=False,
            handoff_targets=("rag", "chat"),
            provides=("kb_route",),
        ),
        build_kb_router_graph,
    )
    registry.register(
        AgentSpec(
            id="chat",
            description="General chat; may call web_search / time tools",
            side_effect="none",
            requires_kb=False,
            handoff_targets=(),
            provides=("chat", "web_search"),
        ),
        _build_chat,
    )
    registry.register(
        AgentSpec(
            id="rag",
            description="Private KB retrieval and grounded answers",
            side_effect="read",
            requires_kb=True,
            handoff_targets=("chat",),
            provides=("kb_read",),
        ),
        _build_rag,
    )
    return registry
