"""Runtime scope Prompt templates retain render and enum-validation boundaries."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.harness.orchestration.intent import IntentAssessment
from src.harness.runtime import scope


@pytest.mark.asyncio
async def test_scope_classifier_renders_only_declared_runtime_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = '{"domain":"knowledge","intent":"knowledge_lookup","risk":"read","confidence":"high","rationale":"internal_docs"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        usage = None

    class FakeCompletions:
        async def create(self, **kwargs: object) -> FakeResponse:
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(scope, "get_client", lambda _cfg: FakeClient())
    monkeypatch.setattr(scope, "pick_model", lambda *_args, **_kwargs: "test-model")

    assessment, _ = await scope._classify_with_llm(
        query="查一下内部项目资料",
        has_bound_kb=False,
        has_routable_kbs=True,
        llm_cfg=SimpleNamespace(provider="openai-compat"),
        source="complex",
        system_prompt_template="tier={{scope_tier}} bound={{has_bound_kb}} candidates={{has_routable_kbs}}",
    )

    messages = captured["messages"]
    assert isinstance(messages, list)
    assert messages[0]["content"] == "tier=高精度 bound=false candidates=true"
    assert assessment is not None
    assert assessment.intent == "knowledge_lookup"


@pytest.mark.asyncio
async def test_scope_trace_records_template_only_when_llm_classification_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_classify(**_kwargs: object) -> tuple[IntentAssessment, float]:
        return (
            IntentAssessment(
                domain="general",
                intent="general_chat",
                risk="none",
                confidence="high",
                source="triage",
            ),
            0.0,
        )

    monkeypatch.setattr(scope, "_classify_with_llm", fake_classify)
    metadata = {"key": "runtime_scope_classification", "version": 2, "digest": "abc", "source": "registry"}
    result = await scope.resolve_runtime_scope(
        messages=[{"role": "user", "content": "这件事怎么处理"}],
        bound_kb=None,
        candidates=[],
        llm_cfg=None,
        mode="rule_triage",
        intent_prompt_metadata=metadata,
    )

    assert result.trace_metadata()["intent_prompt_registry"] == metadata
