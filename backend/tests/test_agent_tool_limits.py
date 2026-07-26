from __future__ import annotations

from typing import Any

import pytest

from src.agent.nodes import call_tools_node
from src.tools.base import Tool, ToolRegistry, ToolResult


class RecordingTool(Tool):
    name = "search_kb"
    description = "test search tool"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(text=f"hit:{kwargs.get('query')}", latency_ms=1)


@pytest.mark.asyncio
async def test_call_tools_node_limits_search_kb_calls_per_step() -> None:
    tool = RecordingTool()
    registry = ToolRegistry()
    registry.register(tool)
    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    state = {
        "messages": [],
        "pending_tool_calls": [
            {"id": f"tc_{i}", "name": "search_kb", "input": {"query": f"q{i}"}}
            for i in range(4)
        ],
        "tool_call_log": [],
    }

    next_state = await call_tools_node(state, registry=registry, emit=emit)

    assert [call["query"] for call in tool.calls] == ["q0", "q1", "q2"]
    assert len(next_state["messages"][-1]["content"]) == 4
    assert next_state["messages"][-1]["content"][-1]["is_error"] is True
    assert "search_kb call limit exceeded: max 3 per step" in (
        next_state["messages"][-1]["content"][-1]["content"]
    )
    assert [evt["event"] for evt in events].count("tool_start") == 3
    assert [evt["event"] for evt in events].count("tool_blocked") == 1
    assert len(next_state["tool_call_log"]) == 4
    assert next_state["pending_tool_calls"] == []
