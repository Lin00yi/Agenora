from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.capabilities.conversations.models import Conversation
from src.capabilities.knowledge.application.routing import (
    _coerce_llm_decision,
    _rule_decision,
    resolve_auto_kb_route_from_candidates,
)
from src.harness.tools.base import ToolResult
from src.harness.tools.kb_search import MultiKBSearchTool


def _kb(kb_id: str, name: str):
    return SimpleNamespace(id=kb_id, name=name, description="")


def test_explicit_multiple_kb_names_route_to_each_named_source() -> None:
    alpha = _kb("kb-alpha", "产品手册")
    beta = _kb("kb-beta", "员工制度")

    decision = _rule_decision("比较产品手册和员工制度的审批要求", [alpha, beta])

    assert decision is not None
    assert decision.needs_retrieval is True
    assert decision.selected_kb_ids == ["kb-alpha", "kb-beta"]
    assert decision.reason == "kb_names_mentioned"


def test_uncertain_multi_candidate_llm_route_does_not_select_any_kb() -> None:
    alpha = _kb("kb-alpha", "产品手册")
    beta = _kb("kb-beta", "员工制度")

    decision = _coerce_llm_decision(
        {"needs_retrieval": True, "selected_kb_ids": [], "confidence": "low"},
        candidates=[alpha, beta],
        latency_ms=1,
        cost_usd=0.0,
    )

    assert decision.needs_retrieval is False
    assert decision.selected_kb_ids == []


@pytest.mark.asyncio
async def test_resolved_rule_route_preserves_all_explicitly_named_kbs(monkeypatch) -> None:
    import src.settings

    monkeypatch.setattr(
        src.settings,
        "get_settings",
        lambda: SimpleNamespace(kb_auto_route_mode="llm_fallback"),
    )
    alpha = _kb("kb-alpha", "产品手册")
    beta = _kb("kb-beta", "员工制度")

    decision = await resolve_auto_kb_route_from_candidates(
        messages=[{"role": "user", "content": "比较产品手册和员工制度"}],
        candidates=[alpha, beta],
        llm_cfg=None,
    )

    assert decision.selected_kb_ids == ["kb-alpha", "kb-beta"]


def test_legacy_bound_conversation_serializes_as_pinned() -> None:
    conv = Conversation(id="conv-1", user_id="user-1", kb_id="kb-alpha")

    assert conv.to_summary_dict()["kb_mode"] == "pinned"


class _FakeKBTool:
    def __init__(self, kb_id: str, kb_name: str, result: ToolResult) -> None:
        self.kb_id = kb_id
        self.kb_name = kb_name
        self._result = result

    async def execute(self, **_kwargs):
        return self._result


@pytest.mark.asyncio
async def test_multi_kb_search_keeps_source_kb_on_each_result() -> None:
    first = _FakeKBTool(
        "kb-alpha",
        "产品手册",
        ToolResult(
            text="[chunk 1] 来源: alpha.md\nalpha evidence",
            latency_ms=3,
            raw={"results": [{"filename": "alpha.md", "doc_id": "doc-a", "score": 0.9}]},
        ),
    )
    second = _FakeKBTool(
        "kb-beta",
        "员工制度",
        ToolResult(
            text="[chunk 1] 来源: beta.md\nbeta evidence",
            latency_ms=4,
            raw={"results": [{"filename": "beta.md", "doc_id": "doc-b", "score": 0.8}]},
        ),
    )

    result = await MultiKBSearchTool([first, second]).execute(query="比较", limit=2)

    assert result.error is None
    assert result.raw["kb_ids"] == ["kb-alpha", "kb-beta"]
    assert [row["kb_id"] for row in result.raw["results"]] == ["kb-alpha", "kb-beta"]
    assert "[知识库：产品手册]" in result.text
    assert "[知识库：员工制度]" in result.text
