"""Regression coverage for the versioned ReAct behavior release gate."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.evaluation.react_runtime import (
    ReactEvaluationError,
    assert_react_quality_gate,
    evaluate_react_cases,
    load_react_cases,
    parse_react_cases_jsonl,
)


CONFIG = Path(__file__).resolve().parents[1] / "config"


async def test_checked_in_react_release_gate_is_green() -> None:
    cases = load_react_cases(CONFIG / "react_eval_cases.jsonl")
    report = await evaluate_react_cases(cases)

    assert report["case_count"] >= 9
    assert report["failed_case_ids"] == []
    assert_react_quality_gate(report)


def test_react_case_parser_rejects_duplicate_ids() -> None:
    fixture = "\n".join(
        [
            '{"id":"duplicate","kind":"order_route","payload":{"messages":[]},"expected":{}}',
            '{"id":"duplicate","kind":"order_route","payload":{"messages":[]},"expected":{}}',
        ]
    )
    with pytest.raises(ReactEvaluationError, match="duplicate case id"):
        parse_react_cases_jsonl(fixture)


def test_react_quality_gate_rejects_behavior_regression() -> None:
    with pytest.raises(ReactEvaluationError, match="behavior gate failed"):
        assert_react_quality_gate({"failed_case_ids": ["dangerous_tool_blocked"]})
