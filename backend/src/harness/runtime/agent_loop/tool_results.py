"""Bound untrusted tool output before it becomes the next model input.

Tools may be provided by MCP/plugins, so a tool's successful response is not
implicitly safe to persist in full or feed to the next ReAct iteration.  The
runtime keeps raw data only until citations/final-result detection is complete,
then carries this compact model-visible representation forward.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.harness.context import estimate_tokens, truncate_text_to_token_budget


_TRUNCATION_NOTICE = "[运行时已截断该工具输出；省略部分未进入后续模型上下文。]"


@dataclass(frozen=True)
class ToolResultBudget:
    truncated_calls: int = 0
    source_tokens: int = 0
    admitted_tokens: int = 0

    def to_state(self) -> dict[str, int]:
        return {
            "truncated_calls": self.truncated_calls,
            "source_tokens": self.source_tokens,
            "admitted_tokens": self.admitted_tokens,
        }


def _compact_text(text: str, *, token_budget: int) -> tuple[str, bool, int, int]:
    source_tokens = estimate_tokens(text)
    if source_tokens <= token_budget:
        return text, False, source_tokens, source_tokens

    notice_tokens = estimate_tokens(_TRUNCATION_NOTICE)
    content_budget = max(1, token_budget - notice_tokens - 12)
    head_budget = max(1, int(content_budget * 0.72))
    tail_budget = max(1, content_budget - head_budget)
    head = truncate_text_to_token_budget(text, head_budget, suffix="")
    # Reverse only for token-aware tail clipping; restore its original order.
    tail = truncate_text_to_token_budget(text[::-1], tail_budget, suffix="")[::-1]
    compacted = f"{head}\n…\n{tail}\n{_TRUNCATION_NOTICE}"
    return compacted, True, source_tokens, estimate_tokens(compacted)


def compact_tool_results(
    results: list[dict[str, Any]],
    *,
    max_tokens_per_call: int,
    max_tokens_per_step: int,
) -> ToolResultBudget:
    """Compact non-final visible result blocks in place, sharing a step budget.

    A fair-share allocation avoids a large first result starving concurrent
    calls. Final-result tools are not fed to another model step, so their
    user-facing report remains intact.
    """
    eligible = [
        item
        for item in results
        if not item.get("hidden_from_trace")
        and not item.get("is_final_result")
        and isinstance(item.get("content"), str)
    ]
    if not eligible:
        return ToolResultBudget()

    per_call = max(1, int(max_tokens_per_call))
    shared = max(1, int(max_tokens_per_step) // len(eligible))
    allocation = min(per_call, shared)
    truncated_calls = 0
    source_tokens = 0
    admitted_tokens = 0
    for item in eligible:
        content, truncated, source, admitted = _compact_text(
            str(item["content"]), token_budget=allocation
        )
        item["content"] = content
        item["result_truncated"] = truncated
        item["result_source_tokens"] = source
        item["result_admitted_tokens"] = admitted
        source_tokens += source
        admitted_tokens += admitted
        truncated_calls += int(truncated)
    return ToolResultBudget(
        truncated_calls=truncated_calls,
        source_tokens=source_tokens,
        admitted_tokens=admitted_tokens,
    )
