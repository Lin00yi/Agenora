from __future__ import annotations

import pytest

from src.tools.search_providers import SearchResult
from src.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_web_search_filters_blank_and_irrelevant_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProvider:
        name = "test"

        async def search(self, query: str, *, max_results: int) -> list[SearchResult]:  # noqa: ARG002
            return [
                SearchResult("Untitled", "https://sz.centanet.com/a", "深圳房价数据"),
                SearchResult("Momenta", "https://momenta.cn/a", "Physical AI company"),
                SearchResult(
                    "深圳二手房成交均价", "https://example.com/shenzhen", "深圳房价和二手房成交走势"
                ),
            ]

    monkeypatch.setattr("src.tools.web_search.get_search_provider", lambda: FakeProvider())

    result = await WebSearchTool(max_results_default=5, max_results_cap=5).execute("深圳房价")

    assert result.raw["count"] == 1
    assert result.raw["results"][0]["title"] == "深圳二手房成交均价"
    assert "Momenta" not in result.text
    assert "Untitled" not in result.text


def test_web_search_policy_has_mode_specific_defaults() -> None:
    from src.context.rag.policy import resolve_web_search_policy

    general = resolve_web_search_policy("general")
    kb = resolve_web_search_policy("kb")

    assert (general.max_calls, general.results_per_call, general.evidence_limit) == (2, 5, 5)
    assert (kb.max_calls, kb.results_per_call, kb.evidence_limit) == (1, 3, 3)
