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


class RecordingWebTool(Tool):
    name = "web_search"
    description = "test web search"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        query = str(kwargs.get("query") or "")
        quality_base = 10 if query == "second" else 0
        results = [
            {
                "title": f"{query}-{index}",
                "url": f"https://example.com/{query}/{index}",
                "body": f"evidence {index}",
                "_quality": quality_base + index,
            }
            for index in range(5)
        ]
        return ToolResult(
            text="untrimmed web evidence",
            latency_ms=1,
            raw={"query": query, "provider": "test", "count": len(results), "results": results},
        )


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


@pytest.mark.asyncio
async def test_call_tools_node_enforces_web_call_and_total_evidence_limits() -> None:
    tool = RecordingWebTool()
    registry = ToolRegistry()
    registry.register(tool)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    state = {
        "messages": [],
        "pending_tool_calls": [
            {"id": "web-1", "name": "web_search", "input": {"query": "first"}},
            {"id": "web-2", "name": "web_search", "input": {"query": "second"}},
            {"id": "web-3", "name": "web_search", "input": {"query": "third"}},
        ],
        "tool_call_log": [],
    }

    next_state = await call_tools_node(
        state,
        registry=registry,
        emit=emit,
        web_search_max_calls=2,
        web_search_evidence_limit=5,
    )

    assert [call["query"] for call in tool.calls] == ["first", "second"]
    tool_results = next_state["messages"][-1]["content"]
    assert tool_results[2]["is_error"] is False
    assert "web search budget exhausted" in tool_results[2]["content"]
    # The second query's higher-quality rows win the whole-response budget.
    assert len(next_state["citations"]) == 5
    assert all("/second/" in citation["url"] for citation in next_state["citations"])
    assert next_state["web_search_call_count"] == 2
    assert next_state["web_search_evidence_count"] == 5
    assert not [event for event in events if event["event"] == "tool_blocked"]
    assert len(next_state["tool_call_log"]) == 2
    web_end_citations = [
        citation
        for event in events
        if event["event"] == "tool_end" and event["name"] == "web_search"
        for citation in event["citations"]
    ]
    assert web_end_citations == next_state["citations"]
