"""Behavioral guardrails for the constrained ReAct tool loop."""
from __future__ import annotations

from typing import Any

import pytest

from src.harness.runtime.agent_loop.call_tools import call_tools_node
from src.harness.runtime.agent_loop.constants import MAX_TOOL_CALLS_PER_TURN
from src.harness.runtime.agent_loop.tool_results import compact_tool_results
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


class _FailingTool(_RecordingTool):
    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(text="", latency_ms=1, error="upstream search timed out")


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


@pytest.mark.asyncio
async def test_react_turn_tool_budget_and_model_history_are_bounded() -> None:
    registry = ToolRegistry()
    tool = _RecordingTool("lookup")
    registry.register(tool)
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    result = await call_tools_node(
        {
            "messages": [{"role": "user", "content": "查询"}],
            "tool_call_count": MAX_TOOL_CALLS_PER_TURN - 1,
            "pending_tool_calls": [
                {"id": "allowed", "name": "lookup", "input": {}},
                {"id": "over-budget", "name": "lookup", "input": {}},
            ],
        },
        registry=registry,
        emit=emit,
    )

    assert len(tool.calls) == 1
    assert result["tool_call_count"] == MAX_TOOL_CALLS_PER_TURN
    assert any(
        event["event"] == "tool_blocked" and event["id"] == "over-budget"
        for event in events
    )
    model_blocks = result["messages"][-1]["content"]
    assert all(set(block) <= {"type", "tool_use_id", "content", "is_error"} for block in model_blocks)


@pytest.mark.asyncio
async def test_blocked_calls_do_not_consume_turn_tool_budget() -> None:
    registry = ToolRegistry()
    dangerous = _RecordingTool("execute_shell")
    allowed = _RecordingTool("lookup")
    registry.register(dangerous)
    registry.register(allowed)

    async def emit(_: dict[str, Any]) -> None:
        return None

    result = await call_tools_node(
        {
            "messages": [{"role": "user", "content": "查询"}],
            "tool_call_count": MAX_TOOL_CALLS_PER_TURN - 1,
            "pending_tool_calls": [
                {"id": "blocked", "name": "execute_shell", "input": {}},
                {"id": "allowed", "name": "lookup", "input": {}},
            ],
        },
        registry=registry,
        emit=emit,
    )

    assert dangerous.calls == []
    assert len(allowed.calls) == 1
    assert result["tool_call_count"] == MAX_TOOL_CALLS_PER_TURN


@pytest.mark.asyncio
async def test_react_tool_loop_persists_the_actual_tool_failure_reason() -> None:
    registry = ToolRegistry()
    tool = _FailingTool("web_search")
    registry.register(tool)

    async def emit(_: dict[str, Any]) -> None:
        return None

    result = await call_tools_node(
        {
            "messages": [{"role": "user", "content": "查询"}],
            "pending_tool_calls": [{"id": "failed-search", "name": "web_search", "input": {}}],
        },
        registry=registry,
        emit=emit,
    )

    assert result["tool_call_log"][-1]["error"] == "upstream search timed out"


def test_tool_results_keep_head_and_tail_under_a_shared_budget() -> None:
    results = [
        {"content": "A" * 20_000},
        {"content": "B" * 20_000},
    ]

    budget = compact_tool_results(
        results,
        max_tokens_per_call=200,
        max_tokens_per_step=300,
    )

    assert budget.truncated_calls == 2
    assert budget.admitted_tokens <= 340  # wrapper/tokenizer rounding allowance
    assert results[0]["content"].startswith("A")
    assert "运行时已截断" in results[0]["content"]
    assert results[1]["content"].startswith("B")


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


def test_runtime_telemetry_reports_budget_without_tool_payloads() -> None:
    telemetry = summarize_runtime_state(
        {
            "tool_call_count": MAX_TOOL_CALLS_PER_TURN,
            "tool_result_budget": {
                "truncated_calls": 1,
                "source_tokens": 4000,
                "admitted_tokens": 1500,
            },
        }
    )

    assert telemetry["tool_call_budget"] == {
        "used": MAX_TOOL_CALLS_PER_TURN,
        "limit": MAX_TOOL_CALLS_PER_TURN,
        "exhausted": True,
    }
    assert telemetry["tool_result_budget"] == {
        "truncated_calls": 1,
        "source_tokens": 4000,
        "admitted_tokens": 1500,
    }
