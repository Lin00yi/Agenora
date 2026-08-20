from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from src.harness.agents import supervisor as supervisor_module
from src.harness.agents.supervisor import build_supervisor_graph
from src.harness.orchestration.dag import MAX_TASKS
from src.harness.orchestration.intent import rule_classify, understand_query
from src.harness.orchestration.planner import resolve_agent_route
from src.harness.orchestration.registry import AgentRegistry, AgentSpec, RuntimeDeps
from src.harness.orchestration.validation import DagValidationError, validate_and_bind
from src.platform.llm.gateway import CostTracker


def test_understanding_preserves_order_and_confirmation_identifiers() -> None:
    query = "  确认退款   RFD-a1b2  "
    understanding = understand_query(query)

    assert understanding.raw_query == query
    assert understanding.order_ids == ()
    assert understanding.approval_ids == ("RFD-A1B2",)
    assert understanding.confirmation_text == "确认退款 RFD-a1b2"


def test_refund_intent_identifies_missing_slots_without_rewrite() -> None:
    assessment = rule_classify(understand_query("我要退 ORD-d0fb0227-1001"))

    assert assessment is not None
    assert assessment.intent == "refund_prepare"
    assert assessment.risk == "write"
    assert assessment.missing_slots == ("refund_reason",)


@pytest.mark.asyncio
async def test_pending_refund_followup_remains_in_orders_domain() -> None:
    registry = AgentRegistry()
    registry.register(
        AgentSpec(id="orders", description="", side_effect="write", provides=("orders_read", "refund_prepare", "refund_confirm")),
        lambda *_args, **_kwargs: (None, CostTracker()),
    )
    registry.register(
        AgentSpec(id="chat", description="", side_effect="none", provides=("chat", "web_search")),
        lambda *_args, **_kwargs: (None, CostTracker()),
    )

    decision = await resolve_agent_route(
        has_kb=False,
        registry=registry,
        user_query="不想要了",
        cost=CostTracker(),
        mode="rule_only",
        pending_refund_followup=True,
    )

    assert decision["target"] == "orders"
    assert decision["reason"] == "pending_refund_followup"


def test_general_dag_accepts_parallel_reads_and_forces_refund_approval() -> None:
    registry = AgentRegistry()
    registry.register(
        AgentSpec(id="chat", description="", side_effect="none", provides=("chat", "web_search")),
        lambda *_args, **_kwargs: (None, CostTracker()),
    )
    registry.register(
        AgentSpec(id="rag", description="", side_effect="read", requires_kb=True, provides=("kb_read",)),
        lambda *_args, **_kwargs: (None, CostTracker()),
    )
    registry.register(
        AgentSpec(id="orders", description="", side_effect="write", provides=("orders_read", "refund_prepare", "refund_confirm")),
        lambda *_args, **_kwargs: (None, CostTracker()),
    )
    payload = {
        "tasks": [
            {"id": "kb", "type": "qa_kb", "depends_on": []},
            {"id": "chat", "type": "qa_chat", "depends_on": []},
            {"id": "refund", "type": "qa_orders", "capabilities": ["refund_confirm"], "depends_on": ["kb", "chat"]},
        ]
    }

    dag = validate_and_bind(payload, registry=registry, has_kb=True)

    assert MAX_TASKS >= 3
    assert [task["agent"] for task in dag["tasks"]] == ["rag", "chat", "orders"]
    assert dag["tasks"][2]["requires_approval"] is True

    with pytest.raises(DagValidationError, match="earlier task"):
        validate_and_bind(
            {"tasks": [{"id": "later", "type": "qa_chat", "depends_on": ["first"]}, {"id": "first", "type": "qa_chat", "depends_on": []}]},
            registry=registry,
            has_kb=True,
        )


class _ParallelGraph:
    def __init__(self, name: str, started: list[str]) -> None:
        self.name = name
        self.started = started

    async def ainvoke(self, _state: dict) -> dict:
        self.started.append(self.name)
        await asyncio.sleep(0.05)
        return {
            "messages": [{"role": "assistant", "content": self.name}],
            "final_report": f"{self.name} result",
            "report_streamed": False,
            "citations": [],
            "tool_call_log": [],
            "retrieved_evidence": [],
            "cost_usd": 0.01,
        }


@pytest.mark.asyncio
async def test_supervisor_runs_independent_read_tasks_in_parallel(monkeypatch) -> None:
    started: list[str] = []
    registry = AgentRegistry()

    def build(name: str):
        def _builder(_deps, **_kwargs):
            return _ParallelGraph(name, started), CostTracker()
        return _builder

    registry.register(AgentSpec(id="chat", description="", side_effect="none", provides=("chat", "web_search")), build("chat"))
    registry.register(AgentSpec(id="rag", description="", side_effect="read", requires_kb=True, provides=("kb_read",)), build("rag"))

    async def fake_route(**_kwargs):
        return {
            "tasks": [
                {"id": "kb", "type": "qa_kb", "capabilities": ["kb_read"], "depends_on": [], "agent": "rag"},
                {"id": "chat", "type": "qa_chat", "capabilities": ["chat", "web_search"], "depends_on": [], "agent": "chat"},
            ],
            "target": "rag",
            "reason": "parallel_reads",
            "source": "rule",
            "confidence": "high",
            "latency_ms": 0,
            "intent": {"risk": "read"},
        }

    monkeypatch.setattr(supervisor_module, "resolve_agent_route", fake_route)
    graph, _cost = build_supervisor_graph(
        registry=registry,
        deps=RuntimeDeps(emit=lambda _event: asyncio.sleep(0), kb=SimpleNamespace(id="kb")),
        allow_rag_chat_handoff=False,
    )
    started_at = time.perf_counter()
    out = await graph.ainvoke({"messages": [{"role": "user", "content": "并行测试"}], "base_messages": [{"role": "user", "content": "并行测试"}]})
    elapsed = time.perf_counter() - started_at

    assert sorted(started) == ["chat", "rag"]
    assert elapsed < 0.09
    assert out["task_status"] == {"kb": "done", "chat": "done"}
    assert "## rag" in out["final_report"]
    assert "## chat" in out["final_report"]
