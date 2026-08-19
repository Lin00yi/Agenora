"""Pluggable agent registry + supervisor routing tests."""
from __future__ import annotations

from typing import Any

import pytest

from src.agents import build_chat_graph, build_graph, build_rag_graph
from src.planning.planner import choose_initial_agent
from src.agents.supervisor import build_supervisor_graph, should_handoff_to_chat
from src.agents.registry import AgentRegistry, AgentSpec, RuntimeDeps, build_default_agent_registry


def test_default_registry_has_chat_and_rag() -> None:
    reg = build_default_agent_registry()
    assert set(reg.ids()) == {"chat", "rag"}
    assert reg.get("chat").requires_kb is False
    assert reg.get("rag").requires_kb is True
    assert "chat" in reg.get("rag").handoff_targets
    assert set(reg.get("chat").provides) == {"chat", "web_search"}
    assert set(reg.get("rag").provides) == {"kb_read"}


def test_registry_available_filters_kb() -> None:
    reg = build_default_agent_registry()
    assert reg.available(has_kb=False) == ["chat"]
    assert set(reg.available(has_kb=True)) == {"chat", "rag"}


def test_registry_rejects_duplicate() -> None:
    reg = AgentRegistry()

    def _builder(_deps: RuntimeDeps, *, emit=None):  # noqa: ANN001
        raise AssertionError("unused")

    reg.register(AgentSpec(id="chat", description="x"), _builder)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(AgentSpec(id="chat", description="y"), _builder)


def test_choose_initial_agent_preserves_legacy_defaults() -> None:
    reg = build_default_agent_registry()
    assert choose_initial_agent(has_kb=True, registry=reg) == ("rag", "empty_query_kb_bound")
    assert choose_initial_agent(has_kb=False, registry=reg) == ("chat", "unbound_default")


def test_choose_initial_agent_routes_chitchat_to_chat_when_kb_bound() -> None:
    reg = build_default_agent_registry()
    assert choose_initial_agent(
        has_kb=True, registry=reg, user_query="你好"
    ) == ("chat", "kb_bound_non_kb_intent")
    # Ambiguous KB questions fall back synchronously without awaiting triage.
    assert choose_initial_agent(
        has_kb=True, registry=reg, user_query="Agenora 怎么部署？"
    ) == ("rag", "kb_bound_default")


def test_handoff_rules() -> None:
    reg = build_default_agent_registry()
    base: dict[str, Any] = {
        "last_agent": "rag",
        "handoff_count": 0,
        "retrieved_evidence": [],
        "query_policy_action": "direct",
    }
    ok, reason = should_handoff_to_chat(
        base, allow_rag_chat_handoff=True, registry=reg
    )
    assert ok is True
    assert reason == "rag_empty_evidence"

    blocked, _ = should_handoff_to_chat(
        base, allow_rag_chat_handoff=False, registry=reg
    )
    assert blocked is False

    with_hits = {**base, "retrieved_evidence": [{"id": "1", "text": "x"}]}
    no, reason2 = should_handoff_to_chat(
        with_hits, allow_rag_chat_handoff=True, registry=reg
    )
    assert no is False
    assert reason2 == "has_evidence"


def test_chat_and_compat_graphs_compile() -> None:
    chat, _ = build_chat_graph()
    assert hasattr(chat, "ainvoke")
    compat, _ = build_graph()
    assert hasattr(compat, "ainvoke")


def test_rag_graph_requires_kb() -> None:
    with pytest.raises(ValueError, match="requires kb"):
        build_rag_graph(kb=None)


def test_supervisor_graph_compiles() -> None:
    graph, _ = build_supervisor_graph(allow_rag_chat_handoff=False)
    assert hasattr(graph, "ainvoke")


@pytest.mark.asyncio
async def test_supervisor_routes_unbound_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, Any]] = []

    class DummyGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                **state,
                "final_report": "hello from chat",
                "cost_usd": 0.01,
                "citations": [],
                "report_streamed": False,
            }

    reg = build_default_agent_registry()

    def fake_chat(deps: RuntimeDeps, *, emit=None):  # noqa: ANN001
        return DummyGraph(), object()

    reg._builders["chat"] = fake_chat  # noqa: SLF001
    reg._builders["rag"] = fake_chat  # noqa: SLF001

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    graph, _ = build_supervisor_graph(
        emit=emit,
        registry=reg,
        allow_rag_chat_handoff=False,
        kb=None,
    )
    out = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "base_messages": [{"role": "user", "content": "hi"}],
            "iterations": 0,
            "tool_call_log": [],
            "citations": [],
            "agent_results": {},
            "handoff_count": 0,
            "supervisor_trace": [],
        }
    )
    assert out["final_report"] == "hello from chat"
    assert out["last_agent"] == "chat"
    assert any(
        e.get("event") == "dag_ready"
        and (e.get("tasks") or [{}])[0].get("agent") == "chat"
        for e in events
    )


@pytest.mark.asyncio
async def test_supervisor_handoff_rag_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class TrackingGraph:
        def __init__(self, name: str) -> None:
            self.name = name

        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            calls.append(self.name)
            if self.name == "rag":
                return {
                    **state,
                    "final_report": "kb miss",
                    "retrieved_evidence": [],
                    "query_policy_action": "direct",
                    "cost_usd": 0.01,
                    "citations": [],
                    "report_streamed": False,
                }
            return {
                **state,
                "final_report": "web fallback answer",
                "cost_usd": 0.02,
                "citations": [{"source_type": "web", "title": "x"}],
                "report_streamed": False,
            }

    reg = build_default_agent_registry()

    def build_named(name: str):
        def _builder(deps: RuntimeDeps, *, emit=None):  # noqa: ANN001
            return TrackingGraph(name), object()

        return _builder

    reg._builders["rag"] = build_named("rag")  # noqa: SLF001
    reg._builders["chat"] = build_named("chat")  # noqa: SLF001

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    class FakeKB:
        id = "kb-1"
        name = "Demo"
        description = ""

    graph, _ = build_supervisor_graph(
        emit=emit,
        registry=reg,
        allow_rag_chat_handoff=True,
        kb=FakeKB(),
    )
    out = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "price?"}],
            "base_messages": [{"role": "user", "content": "price?"}],
            "kb_id": "kb-1",
            "iterations": 0,
            "tool_call_log": [],
            "citations": [],
            "agent_results": {},
            "handoff_count": 0,
            "supervisor_trace": [],
        }
    )
    assert calls == ["rag", "chat"]
    assert out["final_report"] == "web fallback answer"
    assert out["last_agent"] == "chat"
    assert out["handoff_count"] == 1
    assert out.get("cost_usd") == pytest.approx(0.03)
    dag_events = [e for e in events if e.get("event") == "dag_ready"]
    assert dag_events
    assert [t.get("agent") for t in dag_events[-1].get("tasks") or []] == ["rag", "chat"]


@pytest.mark.asyncio
async def test_supervisor_planned_rag_then_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Planner DAG qa_kb → qa_chat runs sequentially without the empty-RAG flag."""
    calls: list[str] = []

    class TrackingGraph:
        def __init__(self, name: str) -> None:
            self.name = name

        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            calls.append(self.name)
            if self.name == "rag":
                return {
                    **state,
                    "final_report": "kb answer",
                    "retrieved_evidence": [{"id": "1", "text": "hit"}],
                    "query_policy_action": "direct",
                    "cost_usd": 0.01,
                    "citations": [],
                    "report_streamed": False,
                }
            return {
                **state,
                "final_report": "chat follow-up",
                "cost_usd": 0.02,
                "citations": [],
                "report_streamed": False,
            }

    reg = build_default_agent_registry()

    def build_named(name: str):
        def _builder(deps: RuntimeDeps, *, emit=None):  # noqa: ANN001
            return TrackingGraph(name), object()

        return _builder

    reg._builders["rag"] = build_named("rag")  # noqa: SLF001
    reg._builders["chat"] = build_named("chat")  # noqa: SLF001

    async def fake_resolve(**_kwargs: Any) -> dict[str, Any]:
        return {
            "tasks": [
                {
                    "id": "task_1",
                    "type": "qa_kb",
                    "capabilities": ["kb_read"],
                    "depends_on": [],
                    "agent": "rag",
                    "on_fail": "abort",
                },
                {
                    "id": "task_2",
                    "type": "qa_chat",
                    "capabilities": ["chat", "web_search"],
                    "depends_on": ["task_1"],
                    "agent": "chat",
                    "on_fail": "skip",
                },
            ],
            "target": "rag",
            "reason": "needs_kb_then_web",
            "source": "complex",
            "confidence": "high",
            "latency_ms": 10,
        }

    monkeypatch.setattr("src.agents.supervisor.resolve_agent_route", fake_resolve)

    class FakeKB:
        id = "kb-1"
        name = "Demo"
        description = ""

    graph, _ = build_supervisor_graph(
        registry=reg,
        allow_rag_chat_handoff=False,
        kb=FakeKB(),
    )
    out = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "查库再联网"}],
            "base_messages": [{"role": "user", "content": "查库再联网"}],
            "kb_id": "kb-1",
            "iterations": 0,
            "tool_call_log": [],
            "citations": [],
            "agent_results": {},
            "handoff_count": 0,
            "supervisor_trace": [],
        }
    )
    assert calls == ["rag", "chat"]
    assert out["final_report"] == "chat follow-up"
    assert out["handoff_count"] == 0
    assert [t["id"] for t in (out.get("task_dag") or {}).get("tasks") or []] == [
        "task_1",
        "task_2",
    ]
