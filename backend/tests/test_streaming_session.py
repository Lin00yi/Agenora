from __future__ import annotations

import json

from src.api.streaming.session import (
    _StreamingAssistantDraft,
    _human_interrupt_content,
    _persisted_tool_events,
)
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


def test_streaming_draft_keeps_partial_text_and_redacts_tool_input() -> None:
    draft = _StreamingAssistantDraft()
    draft.observe({"event": "tool_start", "id": "call-1", "name": "lookup_order", "input": {"token": "secret"}})
    draft.observe({"event": "token", "text": "已找到"})
    draft.observe({"event": "tool_end", "id": "call-1", "ok": True, "latency_ms": 12})

    assert draft.content == "已找到"
    assert draft.tools == [
        {"id": "call-1", "name": "lookup_order", "status": "ok", "latency_ms": 12}
    ]


def test_persisted_tool_event_keeps_only_reviewed_dynamic_display_fields() -> None:
    events = _persisted_tool_events(
        [{
            "id": "call-1",
            "name": "inventory_lookup_v2",
            "t0": 1_723_000_000_000,
            "latency_ms": 842,
            "display": {
                "kind": "mcp",
                "label": "查询实时库存",
                "server_id": "inventory",
                "credential": "must-not-persist",
            },
        }]
    )

    assert events[0]["display"] == {
        "kind": "mcp",
        "label": "查询实时库存",
        "server_id": "inventory",
    }
    assert events[0]["t0"] == 1_723_000_000_000
    assert events[0]["latency_ms"] == 842


def test_streaming_marker_round_trips_through_message_public_shape() -> None:
    encoded = Message.encode_tool_call_log([], streaming=True)
    message = Message(id="assistant-1", conversation_id="conversation-1", role="assistant", content="部分回答", tool_call_log=encoded)

    assert message.to_public_dict()["streaming"] is True
