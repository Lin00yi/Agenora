"""Regression coverage for the product-supported chunking contract."""
from __future__ import annotations

from src.capabilities.knowledge.domain.chunker import (
    chunk_text_by_strategy,
    infer_auto_chunk_strategy,
    normalize_chunk_strategy,
)


def test_recursive_chunker_respects_chinese_sentence_boundaries() -> None:
    text = "第一句说明费用。第二句说明退款。第三句说明到账时间。第四句说明手续费。"

    chunks = chunk_text_by_strategy(text, strategy="auto", target=18, max_size=20, overlap=0)

    assert "".join(chunk.replace("\n\n", "") for chunk in chunks) == text
    assert all(chunk.endswith("。") for chunk in chunks)


def test_recursive_overlap_never_exceeds_max_size() -> None:
    text = "甲" * 10 + "\n\n" + "乙" * 10 + "\n\n" + "丙" * 10 + "\n\n" + "丁" * 100

    chunks = chunk_text_by_strategy(text, strategy="auto", target=40, max_size=100, overlap=25)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert chunks[-1] == "丁" * 100


def test_auto_selects_a_real_source_structure() -> None:
    assert infer_auto_chunk_strategy(filename="guide.md", text="# 标题\n\n正文") == "markdown_heading"
    assert infer_auto_chunk_strategy(filename="service.py", text="def run():\n    pass") == "code"
    assert infer_auto_chunk_strategy(
        filename="fees.md", text="| 费用 | 金额 |\n| --- | --- |\n| 开卡 | 5 USDT |"
    ) == "table_aware"
    assert infer_auto_chunk_strategy(filename="https://help.example.com/faq", text="普通说明") == "recursive"


def test_deprecated_strategy_values_are_safe_for_existing_rows() -> None:
    assert normalize_chunk_strategy("recursive") == "auto"
    assert normalize_chunk_strategy("semantic") == "auto"
    assert normalize_chunk_strategy("parent_child") == "markdown_heading"
