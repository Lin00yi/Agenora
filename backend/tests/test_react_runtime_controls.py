"""Behavioral guardrails for the constrained ReAct tool loop."""
from __future__ import annotations

from typing import Any

import pytest

from src.harness.runtime.agent_loop.call_tools import call_tools_node
from src.harness.runtime.telemetry import summarize_runtime_state
from src.harness.tools.base import Tool, ToolRegistry, ToolResult


class _RecordingTool(Tool):
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(text="ok", latency_ms=1, raw={"results": []})


@pytest.mark.asyncio
async def test_react_tool_loop_enforces_kb_per_step_budget() -> None:
    registry = ToolRegistry()
    tool = _RecordingTool("search_kb")
    registry.register(tool)
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    result = await call_tools_node(
        {
            "messages": [{"role": "user", "content": "查资料"}],
            "pending_tool_calls": [
                {"id": f"kb-{index}", "name": "search_kb", "input": {"query": str(index)}}
                for index in range(4)
            ],
        },
        registry=registry,
        emit=emit,
    )

    assert len(tool.calls) == 3
    assert len([event for event in events if event["event"] == "tool_blocked"]) == 1
    assert len(result["tool_call_log"]) == 4


@pytest.mark.asyncio
async def test_react_tool_loop_rejects_dangerous_name_even_if_registered() -> None:
    registry = ToolRegistry()
    tool = _RecordingTool("execute_shell")
    registry.register(tool)
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    await call_tools_node(
        {
            "messages": [{"role": "user", "content": "执行命令"}],
            "pending_tool_calls": [{"id": "danger-1", "name": "execute_shell", "input": {}}],
        },
        registry=registry,
        emit=emit,
    )

    assert tool.calls == []
    assert events[0]["event"] == "tool_blocked"


def test_runtime_telemetry_omits_tool_arguments_and_results() -> None:
    telemetry = summarize_runtime_state(
        {
            "iterations": 2,
            "tool_call_log": [
                {
                    "name": "search_kb",
                    "input": {"query": "private secret"},
                    "result": "private chunk text",
                    "error": None,
                },
                {"name": "web_search", "input": {"query": "sensitive"}, "error": "timeout"},
            ],
            "web_search_call_count": 1,
            "web_search_evidence_count": 3,
            "runtime_scope": {
                "kind": "knowledge_base",
                "selected_kb_ids": ["kb-1"],
                "route": {"source": "llm", "reason": "matched", "unsafe": "omit me"},
            },
        }
    )

    assert telemetry == {
        "iterations": 2,
        "tool_calls": {"search_kb": 1, "web_search": 1},
        "tool_call_total": 2,
        "tool_error_total": 1,
        "web_search_calls": 1,
        "web_search_evidence": 3,
        "scope": {
            "kind": "knowledge_base",
            "selected_kb_ids": ["kb-1"],
            "route": {"source": "llm", "reason": "matched"},
        },
    }
