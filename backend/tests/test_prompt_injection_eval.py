"""Offline eval harness for prompt-injection rules (YAML + JSONL cases)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.safety.prompt_injection import assess_prompt_injection, reload_prompt_injection_rules

_CASES = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompt_injection_eval_cases.jsonl"
)

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _load_cases() -> list[dict]:
    rows: list[dict] = []
    for line in _CASES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


@pytest.fixture(autouse=True)
def _reload_rules() -> None:
    reload_prompt_injection_rules()


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_prompt_injection_eval_case(case: dict) -> None:
    assessment = assess_prompt_injection(case["text"])
    level = assessment.level
    if "expect_min_level" in case:
        assert _LEVEL_RANK[level] >= _LEVEL_RANK[case["expect_min_level"]], (
            f"{case['id']}: expected >= {case['expect_min_level']}, got {level} "
            f"reasons={assessment.reasons}"
        )
    if "expect_max_level" in case:
        assert _LEVEL_RANK[level] <= _LEVEL_RANK[case["expect_max_level"]], (
            f"{case['id']}: expected <= {case['expect_max_level']}, got {level} "
            f"reasons={assessment.reasons}"
        )
    wanted = case.get("expect_reasons_any") or []
    if wanted:
        assert any(r in assessment.reasons for r in wanted), (
            f"{case['id']}: expected one of {wanted}, got {assessment.reasons}"
        )
