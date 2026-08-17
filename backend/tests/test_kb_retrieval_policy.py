from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.tools.kb_search import KBSearchTool


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    from src.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class RecordingStore:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.limits: list[int] = []

    async def collection_supports_hybrid(self, _collection: str) -> bool:
        return False

    async def search(self, _vector: list[float], **kwargs: Any) -> list[dict[str, Any]]:
        self.limits.append(int(kwargs["limit"]))
        return list(self.hits)


def _tool() -> KBSearchTool:
    return KBSearchTool(
        SimpleNamespace(
            id="kb-id",
            name="Roogoo",
            description="support knowledge",
            collection_name="kb_roogoo",
            is_system=False,
            grouping_enabled=False,
        )
    )


def _hit(index: int, score: float) -> dict[str, Any]:
    return {
        "id": f"chunk-{index}",
        "score": score,
        "payload": {
            "filename": f"source-{index}.md",
            "text": f"evidence {index}",
            "doc_id": f"doc-{index}",
            "enabled": True,
            "doc_enabled": True,
        },
    }


def test_query_policy_and_tool_share_the_configured_final_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agent.nodes.query_policy import _coerce_kb_queries
    from src.infra.retrieval_policy import resolve_kb_retrieval_policy
    from src.settings import get_settings

    monkeypatch.setenv("KB_RETRIEVAL_CANDIDATE_LIMIT", "1")
    monkeypatch.setenv("KB_RETRIEVAL_FINAL_LIMIT", "2")
    monkeypatch.setenv("KB_KG_SKIP_IF_DENSE_SCORE_GE", "0.81")
    get_settings.cache_clear()

    policy = resolve_kb_retrieval_policy()

    assert policy.final_limit == 2
    assert policy.candidate_limit == 2
    assert policy.kg_skip_if_dense_score_ge == pytest.approx(0.81)
    assert _coerce_kb_queries([{"query": "Roogoo 卡片", "limit": 9}], "fallback") == [
        {"query": "Roogoo 卡片", "limit": 2}
    ]


@pytest.mark.asyncio
async def test_kb_search_uses_six_candidates_and_admits_at_most_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.settings import get_settings

    monkeypatch.setenv("KB_RETRIEVAL_CANDIDATE_LIMIT", "6")
    monkeypatch.setenv("KB_RETRIEVAL_FINAL_LIMIT", "3")
    monkeypatch.setenv("KB_RETRIEVAL_MIN_DENSE_SCORE", "0.4")
    get_settings.cache_clear()
    store = RecordingStore([_hit(index, 0.9 - index * 0.01) for index in range(6)])

    async def fake_embed(_query: str, **_kwargs: Any) -> list[float]:
        return [1.0, 0.0]

    monkeypatch.setattr("src.tools.kb_search.embed", fake_embed)
    monkeypatch.setattr("src.tools.kb_search.get_store", lambda: store)

    result = await _tool().execute("Roogoo 卡片费用", limit=9)

    assert store.limits == [6]
    assert result.raw["hits"] == 3
    assert len(result.raw["results"]) == 3
    assert result.text.count("[chunk ") == 3


@pytest.mark.asyncio
async def test_kb_search_rejects_low_similarity_candidates_before_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.settings import get_settings

    monkeypatch.setenv("KB_RETRIEVAL_MIN_DENSE_SCORE", "0.4")
    get_settings.cache_clear()
    store = RecordingStore([_hit(1, 0.39), _hit(2, 0.34)])

    async def fake_embed(_query: str, **_kwargs: Any) -> list[float]:
        return [1.0, 0.0]

    monkeypatch.setattr("src.tools.kb_search.embed", fake_embed)
    monkeypatch.setattr("src.tools.kb_search.get_store", lambda: store)

    result = await _tool().execute("去死吧 Roogoo")

    assert result.raw["hits"] == 0
    assert result.raw["results"] == []
    assert result.raw["candidate_hits"] == 2
    assert result.raw["max_score"] == pytest.approx(0.39)
    assert "准入阈值 0.400" in result.text
