"""Regression coverage for single-agent runtime scope semantics."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.harness.runtime.scope import resolve_runtime_scope


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
