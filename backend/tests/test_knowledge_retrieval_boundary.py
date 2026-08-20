"""RAG application-service boundary tests for future runtime adapters."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.capabilities.knowledge.application import retrieval
from src.capabilities.knowledge.application.retrieval import (
    KnowledgeRetrievalResult,
    RetrievalAssessment,
    RetrievedEvidence,
)
from src.harness.context.rag.assess import RetrievalAssessment as LegacyRetrievalAssessment
from src.harness.context.rag.policy import resolve_kb_retrieval_policy as legacy_policy
from src.harness.tools.kb_search import KBSearchTool


class _Store:
    async def search(self, _vector, **_kwargs):
        return [
            {
                "score": 0.91,
                "payload": {"filename": "guide.md", "text": "可信证据", "doc_id": "doc-1"},
            },
            {
                "score": 0.99,
                "payload": {"filename": "disabled.md", "text": "不可用", "enabled": False},
            },
            {
                "score": 0.2,
                "payload": {"filename": "weak.md", "text": "低相关"},
            },
        ]


@pytest.mark.asyncio
async def test_retrieval_service_returns_structured_admitted_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        kb_retrieval_final_limit=3,
        kb_retrieval_candidate_limit=6,
        kb_retrieval_min_dense_score=0.4,
        kb_kg_skip_if_dense_score_ge=0.7,
        kb_rerank_skip_if_score_ge=0.7,
    )

    async def embed_query(_query: str, *, cfg=None):
        assert cfg is None
        return [0.1, 0.2]

    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    monkeypatch.setattr(retrieval, "embed", embed_query)
    monkeypatch.setattr(retrieval, "get_store", lambda: _Store())
    kb = SimpleNamespace(
        id="kb-1",
        name="产品资料",
        collection_name="kb-1-collection",
        grouping_enabled=False,
        is_system=False,
    )

    result = await retrieval.retrieve_knowledge_evidence(kb=kb, query="产品怎么使用")

    assert result.error is None
    assert result.status == "hit"
    assert result.assessment.candidate_count == 2
    assert result.assessment.admitted_count == 1
    assert result.evidence == (RetrievedEvidence("guide.md", "可信证据", 0.91, "doc-1"),)


@pytest.mark.asyncio
async def test_langgraph_adapter_preserves_tool_result_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    kb = SimpleNamespace(id="kb-1", name="产品资料", description="", is_system=False)
    tool = KBSearchTool(kb)
    result = KnowledgeRetrievalResult(
        kb_id="kb-1",
        kb_name="产品资料",
        evidence=(RetrievedEvidence("guide.md", "可信证据", 0.91, "doc-1"),),
        assessment=RetrievalAssessment("hit", 2, 1, 0.91, 0.4),
    )

    async def retrieve(*, query: str, limit: int = 3):
        assert query == "产品怎么使用"
        assert limit == 3
        return result

    monkeypatch.setattr(tool, "retrieve", retrieve)
    tool_result = await tool.execute("产品怎么使用")

    assert "[chunk 1] 来源: guide.md" in tool_result.text
    assert tool_result.raw == {
        "hits": 1,
        "kb_id": "kb-1",
        "truncated": False,
        "results": [{"filename": "guide.md", "score": 0.91, "doc_id": "doc-1", "text_preview": "可信证据"}],
        "candidate_hits": 2,
        "max_score": 0.91,
        "min_dense_score": 0.4,
        "retrieval_status": "hit",
    }


def test_legacy_harness_imports_reuse_the_knowledge_policy_types() -> None:
    assert LegacyRetrievalAssessment is RetrievalAssessment
    assert legacy_policy.__module__ == "src.capabilities.knowledge.application.retrieval"
