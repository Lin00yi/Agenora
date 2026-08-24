"""Trace IO preview capture for admin spans."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.platform.observability import tracer


@pytest.mark.asyncio
async def test_traced_decorator_captures_agent_state_io(monkeypatch) -> None:
    monkeypatch.setattr(tracer, "tracing_active", lambda: True)
    monkeypatch.setattr(
        tracer,
        "get_settings",
        lambda: SimpleNamespace(trace_enabled=False, trace_store_io=True),
    )
    monkeypatch.setattr(tracer, "get_langfuse", lambda: None)

    @tracer.traced("demo_reason")
    async def demo_reason(state: dict) -> dict:
        return {
            **state,
            "iterations": 1,
            "pending_tool_calls": [{"name": "search_kb", "arguments": {"query": "redis"}}],
            "final_report": "done",
        }

    trace = tracer.start_trace("test", input="hello")
    assert trace is not None
    await demo_reason({"messages": [{"role": "user", "content": "hello"}], "iterations": 0})
    obs = next(item for item in trace.observations if item.name == "demo_reason")
    assert obs.input_preview is not None
    assert "message_count" in obs.input_preview
    assert obs.output_preview is not None
    assert "search_kb" in obs.output_preview
    assert "done" in obs.output_preview
    await trace.finish()


@pytest.mark.asyncio
async def test_scope_span_records_input_output(monkeypatch) -> None:
    monkeypatch.setattr(tracer, "tracing_active", lambda: True)
    monkeypatch.setattr(
        tracer,
        "get_settings",
        lambda: SimpleNamespace(trace_enabled=False, trace_store_io=True),
    )
    monkeypatch.setattr(tracer, "get_langfuse", lambda: None)

    trace = tracer.start_trace("test")
    assert trace is not None
    from src.harness.agents.react import build_react_graph

    graph, _ = build_react_graph()
    scope_node = graph.get_graph().nodes["scope"].data
    await scope_node.afunc({"messages": [{"role": "user", "content": "hi"}]})
    scope_obs = next(obs for obs in trace.observations if obs.name == "scope")
    assert scope_obs.input_preview is not None
    assert "message_count" in scope_obs.input_preview
    assert scope_obs.output_preview is not None
    assert "general" in scope_obs.output_preview
    await trace.finish()
