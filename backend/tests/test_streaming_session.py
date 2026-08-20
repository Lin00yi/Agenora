from __future__ import annotations

import json

from src.api.streaming.session import _human_interrupt_content
from src.capabilities.conversations.models import Message


def test_human_interrupt_persists_its_prompt_as_assistant_content() -> None:
    assert _human_interrupt_content({"prompt": "请选择要退款的订单。"}) == "请选择要退款的订单。"
    assert _human_interrupt_content({"prompt": "   "}) == "请补充继续处理所需的信息。"


def test_human_interrupt_metadata_can_durably_carry_context_trace() -> None:
    trace = {"runtime": {"mode": "general", "agent_runtime": "supervisor"}}
    encoded = Message.encode_tool_call_log(
        [{"name": "human_input_required", "input": {"slot": "order_id"}}],
        memory_trace=trace,
    )

    assert json.loads(encoded or "{}") == {
        "tools": [{"name": "human_input_required", "input": {"slot": "order_id"}}],
        "memory_trace": trace,
    }
