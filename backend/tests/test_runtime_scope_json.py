"""Regression coverage for runtime-scope JSON extraction and LLM fallback."""
from __future__ import annotations

import pytest

from src.harness.runtime.scope import _classify_with_llm, _extract_json_object


def test_extract_json_object_handles_wrapped_json() -> None:
    payload = _extract_json_object('Sure.\n```json\n{"domain":"general","intent":"general_chat"}\n```')
    assert payload["domain"] == "general"


def test_extract_json_object_handles_prose_wrapped_object() -> None:
    payload = _extract_json_object(
        'classification: {"domain":"orders","intent":"order_lookup","risk":"read","confidence":"high"}'
    )
    assert payload["intent"] == "order_lookup"


def test_extract_json_object_rejects_empty_response() -> None:
    with pytest.raises(ValueError, match="empty runtime scope response"):
        _extract_json_object("")


@pytest.mark.asyncio
async def test_classify_with_llm_returns_none_on_empty_response(monkeypatch) -> None:
    from types import SimpleNamespace

    class _FakeMessage:
        content = ""

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]
        usage = None

    class _FakeCompletions:
        async def create(self, **_kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr("src.harness.runtime.scope.get_client", lambda _cfg: _FakeClient())
    monkeypatch.setattr("src.harness.runtime.scope.pick_model", lambda *_args, **_kwargs: "test-model")

    assessment, cost = await _classify_with_llm(
        query="查一下订单",
        has_bound_kb=False,
        has_routable_kbs=False,
        llm_cfg=SimpleNamespace(provider="deepseek"),
        source="triage",
    )

    assert assessment is None
