"""Deterministic golden-set evaluation for the constrained ReAct runtime.

This intentionally executes production routing, tool-budget, and telemetry
code.  It is not an LLM-as-a-judge suite: a green gate proves stable safety
and capability boundaries, while live RAG quality remains covered separately.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.harness.runtime.agent_loop.call_tools import call_tools_node
from src.harness.runtime.intent_routing import requires_order_workflow
from src.harness.runtime.telemetry import summarize_runtime_state
from src.harness.tools.base import Tool, ToolRegistry, ToolResult


class ReactEvaluationError(ValueError):
    """Raised for invalid fixtures or a failed ReAct behavior gate."""


CaseKind = Literal["order_route", "tool_calls", "telemetry"]
_CASE_KINDS = frozenset({"order_route", "tool_calls", "telemetry"})


@dataclass(frozen=True)
class ReactGoldenCase:
    id: str
    kind: CaseKind
    payload: dict[str, Any]
    expected: dict[str, Any]


class _EvaluationTool(Tool):
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"evaluation tool: {name}"
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        # Empty web/KB result shape exercises the real evidence limiter without
        # requiring a network, provider, or test database.
        return ToolResult(text="ok", latency_ms=0, raw={"results": []})


def parse_react_cases_jsonl(text: str, *, source: str = "react-golden-set") -> list[ReactGoldenCase]:
    cases: list[ReactGoldenCase] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReactEvaluationError(f"{source}:{number}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise ReactEvaluationError(f"{source}:{number}: case must be an object")
        case_id = str(raw.get("id") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if not case_id or kind not in _CASE_KINDS:
            raise ReactEvaluationError(f"{source}:{number}: id and supported kind are required")
        if case_id in seen:
            raise ReactEvaluationError(f"{source}:{number}: duplicate case id {case_id}")
        payload = raw.get("payload")
        expected = raw.get("expected")
        if not isinstance(payload, dict) or not isinstance(expected, dict):
            raise ReactEvaluationError(f"{source}:{number}: payload and expected must be objects")
        seen.add(case_id)
        cases.append(ReactGoldenCase(case_id, kind, payload, expected))  # type: ignore[arg-type]
    if not cases:
        raise ReactEvaluationError(f"{source}: no evaluation cases")
    return cases


def load_react_cases(path: str | Path) -> list[ReactGoldenCase]:
    source = Path(path)
    return parse_react_cases_jsonl(source.read_text(encoding="utf-8"), source=str(source))


def _messages(value: object, *, case_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ReactEvaluationError(f"case {case_id}: messages must be an object list")
    return [dict(item) for item in value]


async def _evaluate_tool_calls(case: ReactGoldenCase) -> dict[str, Any]:
    names = case.payload.get("registered_tools") or []
    pending = case.payload.get("pending_tool_calls") or []
    if not isinstance(names, list) or not all(isinstance(name, str) and name for name in names):
        raise ReactEvaluationError(f"case {case.id}: registered_tools must be a string list")
    if not isinstance(pending, list) or not all(isinstance(call, dict) for call in pending):
        raise ReactEvaluationError(f"case {case.id}: pending_tool_calls must be an object list")
    registry = ToolRegistry()
    tools: dict[str, _EvaluationTool] = {}
    for name in names:
        tool = _EvaluationTool(name)
        registry.register(tool)
        tools[name] = tool
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    result = await call_tools_node(
        {
            "messages": _messages(case.payload.get("messages") or [{"role": "user", "content": "test"}], case_id=case.id),
            "pending_tool_calls": [dict(call) for call in pending],
            "web_search_call_count": int(case.payload.get("web_search_call_count") or 0),
            "web_search_evidence_count": int(case.payload.get("web_search_evidence_count") or 0),
        },
        registry=registry,
        emit=emit,
        web_search_max_calls=case.payload.get("web_search_max_calls"),
        web_search_evidence_limit=case.payload.get("web_search_evidence_limit"),
    )
    return {
        "executed": {name: len(tool.calls) for name, tool in sorted(tools.items())},
        "blocked": [str(event.get("name")) for event in events if event.get("event") == "tool_blocked"],
        "web_search_calls": int(result.get("web_search_call_count") or 0),
        "web_search_evidence": int(result.get("web_search_evidence_count") or 0),
    }


async def evaluate_react_cases(cases: list[ReactGoldenCase]) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    for case in cases:
        if case.kind == "order_route":
            actual: dict[str, Any] = {
                "requires_order_workflow": requires_order_workflow(
                    _messages(case.payload.get("messages"), case_id=case.id)
                )
            }
        elif case.kind == "tool_calls":
            actual = await _evaluate_tool_calls(case)
        else:
            state = case.payload.get("state")
            if not isinstance(state, dict):
                raise ReactEvaluationError(f"case {case.id}: telemetry state must be an object")
            actual = summarize_runtime_state(state)
        passed = actual == case.expected
        per_case.append(
            {
                "id": case.id,
                "kind": case.kind,
                "passed": passed,
                "expected": case.expected,
                "actual": actual,
            }
        )
    failures = [row["id"] for row in per_case if not row["passed"]]
    return {
        "schema_version": 1,
        "case_count": len(cases),
        "passed_count": len(cases) - len(failures),
        "failed_case_ids": failures,
        "per_case": per_case,
    }


def assert_react_quality_gate(report: dict[str, Any], *, max_failures: int = 0) -> None:
    failures = list(report.get("failed_case_ids") or [])
    if len(failures) > max(0, int(max_failures)):
        raise ReactEvaluationError(
            f"ReAct behavior gate failed: {len(failures)} failures > {max_failures}: {', '.join(failures)}"
        )


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
