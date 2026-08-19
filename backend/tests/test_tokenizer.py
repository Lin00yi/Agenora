"""Tests for tiktoken-backed context budgeting."""
from __future__ import annotations

from src.models.tokenizer import (
    TOKEN_COUNT_PAD,
    count_tokens,
    encoding_name_for_model,
    heuristic_estimate_tokens,
    token_model_scope,
    truncate_to_token_budget,
)


def test_encoding_name_for_model_families() -> None:
    assert encoding_name_for_model("gpt-4o-mini") == "o200k_base"
    assert encoding_name_for_model("gpt-4-turbo") == "cl100k_base"
    assert encoding_name_for_model("deepseek-v4-flash") == "cl100k_base"
    assert encoding_name_for_model("claude-sonnet-4-6") == "cl100k_base"
    assert encoding_name_for_model(None) == "cl100k_base"


def test_tiktoken_count_is_below_old_cjk_heuristic_for_chinese() -> None:
    text = "项目必须统一使用 PostgreSQL，并且以后请用中文简洁回复。" * 20
    real = count_tokens(text, model="deepseek-v4-flash")
    heuristic = heuristic_estimate_tokens(text)
    assert real > 0
    assert real < heuristic
    # Pad is intentional but still far below the old overestimate.
    assert real <= int(heuristic * 0.85)


def test_token_model_scope_selects_encoding() -> None:
    text = "hello world " * 50
    with token_model_scope("gpt-4o"):
        scoped = count_tokens(text)
    direct = count_tokens(text, model="gpt-4o")
    assert scoped == direct


def test_truncate_to_token_budget_keeps_suffix_and_limit() -> None:
    text = "abcdefghij" * 400
    clipped = truncate_to_token_budget(text, 40, suffix="…[已截断]", model="gpt-4o-mini")
    assert clipped.endswith("…[已截断]")
    assert count_tokens(clipped, model="gpt-4o-mini") <= 40
    assert len(clipped) < len(text)


def test_estimate_tokens_public_api_uses_tokenizer() -> None:
    from src.context import estimate_tokens

    text = "用户偏好使用中文回复。" * 30
    assert estimate_tokens(text, model="deepseek-v4-flash") == count_tokens(
        text, model="deepseek-v4-flash"
    )
    assert estimate_tokens(text, model="deepseek-v4-flash") >= int(
        count_tokens(text, model="deepseek-v4-flash") / TOKEN_COUNT_PAD
    )
