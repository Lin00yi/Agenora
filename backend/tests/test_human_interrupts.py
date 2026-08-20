from __future__ import annotations

import asyncio
import json

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from src.harness.agents.supervisor import build_supervisor_graph
from src.harness.contracts.runtime import RunContext, RunIdentity
from src.harness.orchestration.registry import AgentRegistry, AgentSpec, RuntimeDeps
from src.platform.llm.gateway import CostTracker


class _OrdersGraph:
    def __init__(self, calls: list[list[dict]]) -> None:
        self.calls = calls

    async def ainvoke(self, state: dict) -> dict:
        self.calls.append(list(state["messages"]))
        return {
            "messages": [*state["messages"], {"role": "assistant", "content": "已收到退款资料"}],
            "final_report": "已收到退款资料",
            "report_streamed": False,
            "citations": [],
            "tool_call_log": [],
            "retrieved_evidence": [],
            "cost_usd": 0.0,
        }


class _RefundApprovalGraph:
    """Child stand-in that mimics prepare first, then confirm on resume."""

    def __init__(self, calls: list[list[dict]]) -> None:
        self.calls = calls

    async def ainvoke(self, state: dict) -> dict:
        messages = list(state["messages"])
        self.calls.append(messages)
        latest = next(item["content"] for item in reversed(messages) if item["role"] == "user")
        if latest == "确认退款 RFD-TEST-1":
            return {
                "messages": [*messages, {"role": "assistant", "content": "退款已完成"}],
                "final_report": "退款已完成",
                "report_streamed": False,
                "citations": [],
                # A real resumed orders graph receives the old prepare entry
                # and appends the completed confirmation to it. This used to
                # make Supervisor rediscover the old pending confirmation and
                # dispatch forever.
                "tool_call_log": [
                    {
                        "name": "prepare_refund",
                        "result": json.dumps(
                            {
                                "status": "awaiting_confirmation",
                                "approval_id": "RFD-TEST-1",
                                "confirmation_phrase": "确认退款 RFD-TEST-1",
                            }
                        ),
                    },
                    {
                        "name": "confirm_refund",
                        "result": json.dumps({"status": "completed", "approval_id": "RFD-TEST-1"}),
                    },
                ],
                "retrieved_evidence": [],
                "cost_usd": 0.0,
            }
        return {
            "messages": [*messages, {"role": "assistant", "content": "退款待确认"}],
            "final_report": "退款待确认",
            "report_streamed": False,
            "citations": [],
            "tool_call_log": [
                {
                    "name": "prepare_refund",
                    "result": json.dumps(
                        {
                            "status": "awaiting_confirmation",
                            "approval_id": "RFD-TEST-1",
                            "confirmation_phrase": "确认退款 RFD-TEST-1",
                            "order_id": "ORD-TEST-1001",
                            "amount_minor": 12900,
                            "currency": "CNY",
                        }
                    ),
                }
            ],
            "retrieved_evidence": [],
            "cost_usd": 0.0,
        }


@pytest.mark.asyncio
async def test_missing_refund_slots_pause_and_resume_with_langgraph_interrupt(tmp_path) -> None:
    calls: list[list[dict]] = []
    registry = AgentRegistry()

    def build_orders(_deps, **_kwargs):
        return _OrdersGraph(calls), CostTracker()

    registry.register(
        AgentSpec(
            id="orders",
            description="",
            side_effect="write",
            provides=("orders_read", "refund_prepare", "refund_confirm"),
        ),
        build_orders,
    )
    config = {"configurable": {"thread_id": "test-human-interrupt"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph, _cost = build_supervisor_graph(
            registry=registry,
            deps=RuntimeDeps(emit=lambda _event: asyncio.sleep(0)),
            allow_rag_chat_handoff=False,
            checkpointer=saver,
        )
        initial = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": "我要退款"}],
                "base_messages": [{"role": "user", "content": "我要退款"}],
                "human_inputs": {},
                "human_required_slots": [],
                "human_gate_resumed": False,
                "pending_confirmation": None,
            },
            config=config,
        )
        assert initial["__interrupt__"][0].value["slot"] == "order_id"
        assert calls == []

        after_order = await graph.ainvoke(Command(resume="ORD-TEST-1001"), config=config)
        assert after_order["__interrupt__"][0].value["slot"] == "refund_reason"
        assert calls == []

        completed = await graph.ainvoke(Command(resume="商品不符合预期"), config=config)

    assert completed["final_report"] == "已收到退款资料"
    assert len(calls) == 1
    all_user_text = [item["content"] for item in calls[0] if item["role"] == "user"]
    assert all_user_text[-2:] == ["ORD-TEST-1001", "商品不符合预期"]


@pytest.mark.asyncio
async def test_refund_order_interrupt_contains_only_server_resolved_options(tmp_path, monkeypatch) -> None:
    async def fake_options(*, user_id: str | None) -> list[dict]:
        assert user_id == "user-1"
        return [
            {
                "order_id": "ORD-TEST-1001",
                "product_name": "演示商品",
                "status_label": "已支付，待发货",
                "refundable_minor": 12900,
                "currency": "CNY",
            }
        ]

    monkeypatch.setattr("src.harness.agents.supervisor.list_refundable_order_options", fake_options)
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            id="orders",
            description="",
            side_effect="write",
            provides=("orders_read", "refund_prepare", "refund_confirm"),
        ),
        lambda _deps, **_kwargs: (_OrdersGraph([]), CostTracker()),
    )
    config = {"configurable": {"thread_id": "test-human-order-options"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph, _cost = build_supervisor_graph(
            registry=registry,
            deps=RuntimeDeps(
                emit=lambda _event: asyncio.sleep(0),
                run=RunContext(identity=RunIdentity(user_id="user-1")),
            ),
            allow_rag_chat_handoff=False,
            checkpointer=saver,
        )
        paused = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": "我要退款"}],
                "base_messages": [{"role": "user", "content": "我要退款"}],
                "human_inputs": {},
                "human_required_slots": [],
                "human_gate_resumed": False,
                "pending_confirmation": None,
            },
            config=config,
        )

    payload = paused["__interrupt__"][0].value
    assert payload["slot"] == "order_id"
    assert payload["order_options"] == [
        {
            "order_id": "ORD-TEST-1001",
            "product_name": "演示商品",
            "status_label": "已支付，待发货",
            "refundable_minor": 12900,
            "currency": "CNY",
        }
    ]


@pytest.mark.asyncio
async def test_order_selected_after_refund_prompt_pauses_for_reason(tmp_path) -> None:
    """Choosing an order from a refund-oriented list stays in the HITL gate."""
    calls: list[list[dict]] = []
    registry = AgentRegistry()

    def build_orders(_deps, **_kwargs):
        return _OrdersGraph(calls), CostTracker()

    registry.register(
        AgentSpec(
            id="orders",
            description="",
            side_effect="write",
            provides=("orders_read", "refund_prepare", "refund_confirm"),
        ),
        build_orders,
    )
    config = {"configurable": {"thread_id": "test-order-selection-refund"}}
    messages = [
        {"role": "user", "content": "请查询我的订单"},
        {
            "role": "assistant",
            "content": "请选择要退款的订单，并告诉我订单号和退款原因。",
        },
        {"role": "user", "content": "这一笔 ORD-TEST-1001"},
    ]
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph, _cost = build_supervisor_graph(
            registry=registry,
            deps=RuntimeDeps(emit=lambda _event: asyncio.sleep(0)),
            allow_rag_chat_handoff=False,
            checkpointer=saver,
        )
        paused = await graph.ainvoke(
            {
                "messages": messages,
                "base_messages": messages,
                "human_inputs": {},
                "human_required_slots": [],
                "human_gate_resumed": False,
                "pending_confirmation": None,
            },
            config=config,
        )

    assert paused["__interrupt__"][0].value["slot"] == "refund_reason"
    assert calls == []


@pytest.mark.asyncio
async def test_prepare_refund_pauses_for_exact_confirmation_before_resume(tmp_path) -> None:
    calls: list[list[dict]] = []
    registry = AgentRegistry()

    def build_orders(_deps, **_kwargs):
        return _RefundApprovalGraph(calls), CostTracker()

    registry.register(
        AgentSpec(
            id="orders",
            description="",
            side_effect="write",
            provides=("orders_read", "refund_prepare", "refund_confirm"),
        ),
        build_orders,
    )
    config = {"configurable": {"thread_id": "test-refund-confirmation"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph, _cost = build_supervisor_graph(
            registry=registry,
            deps=RuntimeDeps(emit=lambda _event: asyncio.sleep(0)),
            allow_rag_chat_handoff=False,
            checkpointer=saver,
        )
        awaiting_confirmation = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "我要退款，订单号 ORD-TEST-1001，退款原因是商品不符合预期",
                    }
                ],
                "base_messages": [
                    {
                        "role": "user",
                        "content": "我要退款，订单号 ORD-TEST-1001，退款原因是商品不符合预期",
                    }
                ],
                "human_inputs": {},
                "human_required_slots": [],
                "human_gate_resumed": False,
                "pending_confirmation": None,
            },
            config=config,
        )
        prompt = awaiting_confirmation["__interrupt__"][0].value
        assert prompt["slot"] == "refund_confirmation"
        assert prompt["approval_id"] == "RFD-TEST-1"
        assert len(calls) == 1

        completed = await graph.ainvoke(
            Command(resume="确认退款 RFD-TEST-1"), config=config
        )

    assert completed["final_report"] == "退款已完成"
    assert len(calls) == 2
