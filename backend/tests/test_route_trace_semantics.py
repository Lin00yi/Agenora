"""Regression coverage for single-agent runtime scope semantics."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.harness.orchestration.intent import IntentAssessment
from src.harness.runtime.scope import _needs_complex_intent_layer, resolve_runtime_scope


def test_needs_complex_intent_layer_skips_on_high_or_medium_triage() -> None:
    high = IntentAssessment(
        domain="general",
        intent="general_chat",
        risk="none",
        confidence="high",
        source="triage",
    )
    medium = IntentAssessment(
        domain="knowledge",
        intent="knowledge_lookup",
        risk="read",
        confidence="medium",
        source="triage",
    )
    low = IntentAssessment(
        domain="general",
        intent="general_chat",
        risk="none",
        confidence="low",
        source="triage",
    )

    assert _needs_complex_intent_layer(high, scope_mode="layered") is False
    assert _needs_complex_intent_layer(medium, scope_mode="layered") is False
    assert _needs_complex_intent_layer(low, scope_mode="layered") is True
    assert _needs_complex_intent_layer(None, scope_mode="layered") is True
    assert _needs_complex_intent_layer(low, scope_mode="rule_triage") is False


@pytest.mark.asyncio
async def test_layered_skips_complex_when_triage_high_confidence(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_classify(*, source: str, **_kwargs):
        calls.append(source)
        if source == "triage":
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
        raise AssertionError(f"unexpected complex intent pass: {source}")

    monkeypatch.setattr("src.harness.runtime.scope._classify_with_llm", fake_classify)

    scope = await resolve_runtime_scope(
        messages=[{"role": "user", "content": "你好，今天天气怎么样"}],
        bound_kb=None,
        candidates=[],
        llm_cfg=None,
        mode="layered",
    )

    assert calls == ["triage"]
    assert scope.intent.source == "triage"
    assert scope.intent.confidence == "high"


@pytest.mark.asyncio
async def test_layered_runs_complex_when_triage_low_confidence(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_classify(*, source: str, **_kwargs):
        calls.append(source)
        if source == "triage":
            return (
                IntentAssessment(
                    domain="general",
                    intent="general_chat",
                    risk="none",
                    confidence="low",
                    source="triage",
                ),
                0.0,
            )
        if source == "complex":
            return (
                IntentAssessment(
                    domain="knowledge",
                    intent="knowledge_lookup",
                    risk="read",
                    confidence="high",
                    source="complex",
                ),
                0.0,
            )
        raise AssertionError(f"unexpected intent pass: {source}")

    monkeypatch.setattr("src.harness.runtime.scope._classify_with_llm", fake_classify)

    scope = await resolve_runtime_scope(
        messages=[{"role": "user", "content": "帮我查一下内部文档"}],
        bound_kb=None,
        candidates=[],
        llm_cfg=None,
        mode="layered",
    )

    assert calls == ["triage", "complex"]
    assert scope.intent.source == "complex"
    assert scope.intent.confidence == "high"


@pytest.mark.asyncio
async def test_rule_only_general_scope_never_runs_kb_selection(monkeypatch) -> None:
    async def unexpected_kb_route(**_kwargs):
        raise AssertionError("ordinary conversation must not invoke KB routing")

    monkeypatch.setattr("src.harness.runtime.scope.resolve_auto_kb_route_from_candidates", unexpected_kb_route)

    scope = await resolve_runtime_scope(
        messages=[{"role": "user", "content": "你好，帮我润色这句话"}],
        bound_kb=None,
        candidates=[SimpleNamespace(id="kb-1")],
        llm_cfg=None,
        mode="rule_only",
    )

    assert scope.kind == "general"
    assert scope.selected_kbs == ()
    assert scope.intent.source == "fallback"


@pytest.mark.asyncio
async def test_pinned_kb_is_admitted_without_a_second_router_call(monkeypatch) -> None:
    async def unexpected_kb_route(**_kwargs):
        raise AssertionError("pinned KB must not invoke automatic routing")

    monkeypatch.setattr("src.harness.runtime.scope.resolve_auto_kb_route_from_candidates", unexpected_kb_route)
    kb = SimpleNamespace(id="kb-1")
    scope = await resolve_runtime_scope(
        messages=[{"role": "user", "content": "解释一下 Redis"}],
        bound_kb=kb,
        candidates=[],
        llm_cfg=None,
        mode="rule_only",
    )

    assert scope.kind == "knowledge_base"
    assert scope.selected_kbs == (kb,)
    assert scope.kb_route is None
