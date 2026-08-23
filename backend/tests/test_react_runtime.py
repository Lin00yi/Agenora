"""Regression coverage for the default single-agent runtime boundary."""
from __future__ import annotations

from src.harness.agents.react import build_react_graph
from src.harness.runtime.intent_routing import requires_order_workflow


def test_react_runtime_has_one_tool_loop_not_a_supervisor_dag() -> None:
    graph, _ = build_react_graph()
    nodes = set(graph.get_graph().nodes)

    assert {"scope", "reason", "call_tools"} <= nodes
    assert not {"route", "schedule", "dispatch", "review", "query_policy"} & nodes


def test_only_order_intents_or_explicit_refund_followups_leave_react() -> None:
    assert requires_order_workflow([{"role": "user", "content": "帮我查订单 ORD-123"}])
    assert requires_order_workflow([{"role": "user", "content": "查询我的所有订单"}])
    assert requires_order_workflow([{"role": "user", "content": "我要执行退款"}])
    assert requires_order_workflow([{"role": "user", "content": "确认退款 RFD-123"}])
    assert requires_order_workflow(
        [
            {"role": "assistant", "content": "请补充退款原因后继续处理。"},
            {"role": "user", "content": "商品与描述不符"},
        ]
    )
    assert not requires_order_workflow([{"role": "user", "content": "解释一下 Redis 的连接方式"}])
    assert not requires_order_workflow(
        [
            {"role": "assistant", "content": "退款政策通常需要核对订单状态。"},
            {"role": "user", "content": "因为网络慢"},
        ]
    )
