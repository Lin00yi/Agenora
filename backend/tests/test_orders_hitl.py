from __future__ import annotations

import json
from functools import partial

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from src.harness.agents.orders.hitl import (
    extract_pending_confirmation,
    human_input_gate,
    needs_human_gate,
    sync_pending_confirmation,
)
from src.harness.contracts.state import AgentState


@pytest.mark.asyncio
async def test_missing_refund_slots_pause_and_resume_with_langgraph_interrupt(tmp_path) -> None:
    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("human_gate", partial(human_input_gate, user_id=None))
    graph_builder.set_entry_point("human_gate")
    graph_builder.add_conditional_edges(
        "human_gate",
        lambda state: "human_gate" if needs_human_gate(state) else END,
        {"human_gate": "human_gate", END: END},
    )
    config = {"configurable": {"thread_id": "test-human-interrupt"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph = graph_builder.compile(checkpointer=saver)
        initial = await graph.ainvoke(
            {
                "messages": [{"role": "user", "content": "我要退款"}],
                "human_inputs": {},
                "human_required_slots": [],
            },
            config=config,
        )
        assert initial["__interrupt__"][0].value["slot"] == "order_id"

        after_order = await graph.ainvoke(Command(resume="ORD-TEST-1001"), config=config)
        assert after_order["__interrupt__"][0].value["slot"] == "refund_reason"

        completed = await graph.ainvoke(Command(resume="商品不符合预期"), config=config)
        assert completed.get("__interrupt__") is None
        user_text = [item["content"] for item in completed["messages"] if item["role"] == "user"]
        assert user_text[-2:] == ["ORD-TEST-1001", "商品不符合预期"]


@pytest.mark.asyncio
async def test_prepare_refund_result_triggers_refund_confirmation_interrupt(tmp_path) -> None:
    payload = {
        "status": "awaiting_confirmation",
        "approval_id": "RFD-TEST-1",
        "confirmation_phrase": "确认退款 RFD-TEST-1",
        "order_id": "ORD-TEST-1001",
        "amount_minor": 12900,
        "currency": "CNY",
    }
    async def sync_node(state: AgentState) -> AgentState:
        return await sync_pending_confirmation(
            {
                **state,
                "tool_call_log": [
                    {
                        "name": "prepare_refund",
                        "result": json.dumps(payload),
                    }
                ],
            }
        )

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("sync", sync_node)
    graph_builder.add_node("human_gate", partial(human_input_gate, user_id=None))
    graph_builder.set_entry_point("sync")
    graph_builder.add_edge("sync", "human_gate")
    graph_builder.add_conditional_edges(
        "human_gate",
        lambda state: END,
        {END: END},
    )
    config = {"configurable": {"thread_id": "test-refund-confirmation"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        graph = graph_builder.compile(checkpointer=saver)
        paused = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "我要退款，订单号 ORD-TEST-1001，退款原因是商品不符合预期",
                    }
                ],
                "human_inputs": {},
                "human_required_slots": [],
            },
            config=config,
        )
        interrupt_payload = paused["__interrupt__"][0].value
        assert interrupt_payload["slot"] == "refund_confirmation"
        assert interrupt_payload["approval_id"] == "RFD-TEST-1"


def test_extract_pending_confirmation_reads_prepare_refund_json() -> None:
    payload = extract_pending_confirmation(
        [
            {
                "name": "prepare_refund",
                "result": json.dumps(
                    {
                        "status": "awaiting_confirmation",
                        "approval_id": "RFD-1",
                        "confirmation_phrase": "确认退款 RFD-1",
                    }
                ),
            }
        ]
    )
    assert payload is not None
    assert payload["approval_id"] == "RFD-1"
