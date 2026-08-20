"""Opt-in live Provider baseline for first-step ReAct tool selection.

Unlike the deterministic release gate, this sends a small number of real
tool-choice prompts to the configured Provider.  It never executes the tools;
the result is a reviewable quality baseline, not a CI prerequisite.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.harness.prompts.system import SYSTEM_PROMPT_GENERAL
from src.harness.runtime.agent_loop.reason import _prepare_provider_request
from src.harness.tools.base import Tool, ToolRegistry, ToolResult
from src.platform.llm import CostTracker, pick_model
from src.platform.llm.adapters import LLMToolChatResponse, create_tool_adapter
from src.capabilities.settings.domain.models import configured_context_window_for_model


class LiveToolSelectionError(ValueError):
    """Raised for an invalid live baseline fixture or failed acceptance gate."""


@dataclass(frozen=True)
class LiveToolSelectionCase:
    id: str
    messages: tuple[dict[str, Any], ...]
    mounted_tools: tuple[str, ...]
    required_any_tools: frozenset[str]
    forbidden_tools: frozenset[str]
    expected_tool_count: int | None = None


class _SelectionTool(Tool):
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = {
            "get_current_time": "获取服务端当前日期、时间和星期。",
            "web_search": "搜索需要实时或权威来源的公开网页信息。",
            "search_kb": "在当前用户已授权知识库中检索相关文档。",
        }.get(name, f"已授权评测工具：{name}。")

    async def execute(self, **_kwargs: Any) -> ToolResult:
        raise RuntimeError("live tool-selection baseline never executes tools")


def parse_live_tool_cases_jsonl(text: str, *, source: str = "live-tool-selection") -> list[LiveToolSelectionCase]:
    cases: list[LiveToolSelectionCase] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LiveToolSelectionError(f"{source}:{number}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise LiveToolSelectionError(f"{source}:{number}: case must be an object")
        case_id = str(raw.get("id") or "").strip()
        messages = raw.get("messages")
        mounted = raw.get("mounted_tools")
        expected = raw.get("expected")
        if not case_id or not isinstance(messages, list) or not isinstance(mounted, list) or not isinstance(expected, dict):
            raise LiveToolSelectionError(f"{source}:{number}: id, messages, mounted_tools and expected are required")
        if case_id in seen or not all(isinstance(item, dict) for item in messages):
            detail = "duplicate case id" if case_id in seen else "messages must be an object list"
            raise LiveToolSelectionError(f"{source}:{number}: {detail}")
        mounted_names = tuple(str(item).strip() for item in mounted if str(item).strip())
        if not mounted_names or len(set(mounted_names)) != len(mounted_names):
            raise LiveToolSelectionError(f"{source}:{number}: mounted_tools must be a unique non-empty string list")
        required = frozenset(str(item).strip() for item in expected.get("required_any_tools", []) if str(item).strip())
        forbidden = frozenset(str(item).strip() for item in expected.get("forbidden_tools", []) if str(item).strip())
        count = expected.get("tool_count")
        if count is not None and (not isinstance(count, int) or count < 0):
            raise LiveToolSelectionError(f"{source}:{number}: expected.tool_count must be a non-negative integer")
        if not required.issubset(set(mounted_names)) or not forbidden.issubset(set(mounted_names)):
            raise LiveToolSelectionError(f"{source}:{number}: expected tools must be mounted")
        seen.add(case_id)
        cases.append(
            LiveToolSelectionCase(
                id=case_id,
                messages=tuple(dict(item) for item in messages),
                mounted_tools=mounted_names,
                required_any_tools=required,
                forbidden_tools=forbidden,
                expected_tool_count=count,
            )
        )
    if not cases:
        raise LiveToolSelectionError(f"{source}: no evaluation cases")
    return cases


def load_live_tool_cases(path: str | Path) -> list[LiveToolSelectionCase]:
    source = Path(path)
    return parse_live_tool_cases_jsonl(source.read_text(encoding="utf-8"), source=str(source))


async def evaluate_live_tool_selection(
    cases: list[LiveToolSelectionCase],
    *,
    llm_cfg,
    adapter=None,
) -> dict[str, Any]:
    """Ask the Provider for one tool-selection round per case, without execution."""
    if llm_cfg is None:
        raise LiveToolSelectionError("a configured platform or user LLM connection is required")
    provider = adapter or create_tool_adapter(llm_cfg)
    tracker = CostTracker()
    per_case: list[dict[str, Any]] = []
    for case in cases:
        registry = ToolRegistry()
        for name in case.mounted_tools:
            registry.register(_SelectionTool(name))
        schemas = registry.all_schemas()
        messages = [dict(message) for message in case.messages]
        model = pick_model(messages, schemas, llm_cfg)
        system_prompt, provider_messages, max_tokens, _trace = _prepare_provider_request(
            model=model,
            configured_context_window=configured_context_window_for_model(llm_cfg, model),
            base_system_prompt=SYSTEM_PROMPT_GENERAL,
            tools_schema=schemas,
            conversation_messages=messages,
            output_task="answer",
        )
        response: LLMToolChatResponse = await provider.chat_with_tools(
            model=model,
            system_prompt=system_prompt,
            messages=provider_messages,
            tools=schemas,
            max_tokens=max_tokens,
        )
        tracker.add(model, response.usage, cfg=llm_cfg)
        selected = [call.name for call in response.tool_calls]
        selected_set = set(selected)
        passes_required = not case.required_any_tools or bool(selected_set & case.required_any_tools)
        passes_forbidden = not bool(selected_set & case.forbidden_tools)
        passes_count = case.expected_tool_count is None or len(selected) == case.expected_tool_count
        per_case.append(
            {
                "id": case.id,
                "model": model,
                "selected_tools": selected,
                "passed": passes_required and passes_forbidden and passes_count,
                "failure_reasons": [
                    *([] if passes_required else ["required_tool_not_selected"]),
                    *([] if passes_forbidden else ["forbidden_tool_selected"]),
                    *([] if passes_count else ["unexpected_tool_count"]),
                ],
            }
        )
    failed = [row["id"] for row in per_case if not row["passed"]]
    return {
        "schema_version": 1,
        "case_count": len(cases),
        "passed_count": len(cases) - len(failed),
        "failed_case_ids": failed,
        "total_cost_usd": tracker.total_usd,
        "per_case": per_case,
    }


def assert_live_tool_selection_gate(
    report: dict[str, Any],
    *,
    max_failures: int = 0,
    max_total_cost_usd: float | None = None,
) -> None:
    failures = list(report.get("failed_case_ids") or [])
    if len(failures) > max(0, int(max_failures)):
        raise LiveToolSelectionError(
            f"live tool-selection gate failed: {len(failures)} failures > {max_failures}: {', '.join(failures)}"
        )
    total = report.get("total_cost_usd")
    if max_total_cost_usd is not None and (total is None or float(total) > max_total_cost_usd):
        raise LiveToolSelectionError(f"live tool-selection cost {total!r} exceeds {max_total_cost_usd:.6f}")


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
