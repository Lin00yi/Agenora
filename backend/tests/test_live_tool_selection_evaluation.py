"""Offline coverage for the opt-in real-Provider tool selection baseline."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.capabilities.settings.domain.models import UserLLMConfig
from src.harness.evaluation.live_tool_selection import (
    LiveToolSelectionError,
    assert_live_tool_selection_gate,
    evaluate_live_tool_selection,
    load_live_tool_cases,
)
from src.platform.llm.adapters import LLMToolCall, LLMToolChatResponse


CONFIG = Path(__file__).resolve().parents[1] / "config"


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs["tools"])
        index = len(self.calls)
        selected = (
            [LLMToolCall("clock-1", "get_current_time", {})]
            if index == 1
            else [LLMToolCall("web-1", "web_search", {"query": "Python release"})]
            if index == 2
            else []
        )
        return LLMToolChatResponse([], selected, [], usage=None)


async def test_live_baseline_uses_provider_adapter_without_executing_tools() -> None:
    cfg = UserLLMConfig(
        provider="openai-compat",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        default_model="test-model",
        complex_model="test-model",
        context_window=16_000,
    )
    adapter = _Adapter()
    report = await evaluate_live_tool_selection(
        load_live_tool_cases(CONFIG / "react_live_tool_cases.jsonl"),
        llm_cfg=cfg,
        adapter=adapter,
    )

    assert report["failed_case_ids"] == []
    assert len(adapter.calls) == 3
    assert {tool["name"] for tool in adapter.calls[0]} == {"get_current_time", "web_search"}


def test_live_baseline_gate_rejects_failed_or_unpriced_runs() -> None:
    with pytest.raises(LiveToolSelectionError, match="gate failed"):
        assert_live_tool_selection_gate({"failed_case_ids": ["stable_explanation_avoids_tools"]})
    with pytest.raises(LiveToolSelectionError, match="cost"):
        assert_live_tool_selection_gate(
            {"failed_case_ids": [], "total_cost_usd": None},
            max_total_cost_usd=0.1,
        )
