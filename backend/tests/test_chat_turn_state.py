"""Regression coverage for fresh turns on durable LangGraph threads."""
from __future__ import annotations

from src.api.streaming.session import _fresh_turn_state


def test_fresh_turn_state_clears_terminal_and_retrieval_state() -> None:
    state = _fresh_turn_state(
        messages=[{"role": "user", "content": "你好"}],
        kb_id=None,
        mcp_plugin_set_version="set-1",
        prompt_injection_risk="low",
        prompt_injection_reasons=[],
    )

    # These values overwrite identically named values in the previous
    # checkpoint. A non-null final_report would make reason_node early-exit.
    assert state["final_report"] is None
    assert state["report_streamed"] is False
    assert state["pending_tool_calls"] == []
    assert state["tool_call_log"] == []
    assert state["iterations"] == 0
    assert state["kb_context"] == ""
    assert state["retrieved_evidence"] == []
    assert state["citations"] == []
    assert state["cost_usd"] is None
