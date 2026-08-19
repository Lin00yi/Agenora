"""Tests for three-layer supervisor routing (rule → triage → complex)."""
from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from src.runtime.router import (
    choose_initial_agent,
    looks_complex_query,
    resolve_agent_route,
    rule_route,
)
from src.runtime.registry import build_default_agent_registry
from src.infra.llm import CostTracker


def test_rule_route_unbound_is_chat() -> None:
    reg = build_default_agent_registry()
    decision = rule_route(has_kb=False, registry=reg, user_query="怎么部署？")
    assert decision is not None
    assert decision["target"] == "chat"
    assert decision["source"] == "rule"
    assert decision["tasks"][0]["type"] == "qa_chat"
    assert decision["tasks"][0]["agent"] == "chat"


def test_rule_route_chitchat_with_kb() -> None:
    reg = build_default_agent_registry()
    decision = rule_route(has_kb=True, registry=reg, user_query="你好")
    assert decision is not None
    assert decision["target"] == "chat"
    assert decision["source"] == "rule"


def test_rule_route_ambiguous_kb_query_escalates() -> None:
    reg = build_default_agent_registry()
    assert rule_route(has_kb=True, registry=reg, user_query="Agenora 怎么部署？") is None


def test_choose_initial_agent_fallback_when_rule_uncertain() -> None:
    reg = build_default_agent_registry()
    assert choose_initial_agent(
        has_kb=True, registry=reg, user_query="Agenora 怎么部署？"
    ) == ("rag", "kb_bound_default")


def test_looks_complex_query() -> None:
    assert looks_complex_query("短问") is False
    assert looks_complex_query("A？" + "B？" ) is True
    long = "请同时说明部署方式、权限模型、以及本地和私有化差异。" * 3
    assert looks_complex_query(long) is True


@pytest.mark.asyncio
async def test_resolve_rule_only_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = build_default_agent_registry()
    cost = CostTracker()

    async def boom(**_kwargs: Any):
        raise AssertionError("llm should not run in rule_only")

    monkeypatch.setattr("src.runtime.router.llm_route", boom)
    decision = await resolve_agent_route(
        has_kb=True,
        registry=reg,
        user_query="你好",
        cost=cost,
        mode="rule_only",
    )
    assert decision["target"] == "chat"
    assert decision["source"] == "rule"


@pytest.mark.asyncio
async def test_resolve_uses_triage_then_accepts_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = build_default_agent_registry()
    cost = CostTracker()
    calls: list[str] = []

    async def fake_llm_route(**kwargs: Any):
        calls.append(kwargs["source"])
        return {
            "target": "rag",
            "reason": "needs_kb_fact",
            "source": kwargs["source"],
            "confidence": "medium",
            "latency_ms": 12,
        }

    monkeypatch.setattr("src.runtime.router.llm_route", fake_llm_route)
    decision = await resolve_agent_route(
        has_kb=True,
        registry=reg,
        user_query="退款流程是什么",
        cost=cost,
        triage_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="t"),
        complex_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="c"),
        mode="layered",
    )
    assert decision["target"] == "rag"
    assert decision["source"] == "triage"
    assert calls == ["triage"]


@pytest.mark.asyncio
async def test_resolve_escalates_low_confidence_to_complex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = build_default_agent_registry()
    cost = CostTracker()
    calls: list[str] = []

    async def fake_llm_route(**kwargs: Any):
        calls.append(kwargs["source"])
        if kwargs["source"] == "triage":
            return {
                "target": "chat",
                "reason": "unsure",
                "source": "triage",
                "confidence": "low",
                "latency_ms": 8,
            }
        return {
            "target": "rag",
            "reason": "complex_kb",
            "source": "complex",
            "confidence": "high",
            "latency_ms": 20,
        }

    monkeypatch.setattr("src.runtime.router.llm_route", fake_llm_route)
    decision = await resolve_agent_route(
        has_kb=True,
        registry=reg,
        user_query="退款怎么算",
        cost=cost,
        triage_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="t"),
        complex_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="c"),
        mode="layered",
    )
    assert decision["target"] == "rag"
    assert decision["source"] == "complex"
    assert calls == ["triage", "complex"]


@pytest.mark.asyncio
async def test_resolve_complex_query_skips_triage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = build_default_agent_registry()
    cost = CostTracker()
    calls: list[str] = []

    async def fake_llm_route(**kwargs: Any):
        calls.append(kwargs["source"])
        return {
            "target": "rag",
            "reason": "multi_intent",
            "source": kwargs["source"],
            "confidence": "high",
            "latency_ms": 30,
        }

    monkeypatch.setattr("src.runtime.router.llm_route", fake_llm_route)
    query = "请同时对比本地部署、权限模型，以及私有化合规差异？"
    assert looks_complex_query(query)
    decision = await resolve_agent_route(
        has_kb=True,
        registry=reg,
        user_query=query,
        cost=cost,
        triage_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="t"),
        complex_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="c"),
        mode="layered",
    )
    assert decision["source"] == "complex"
    assert calls == ["complex"]
    assert decision["tasks"][0]["type"] == "qa_kb"
    assert decision["tasks"][0]["agent"] == "rag"


@pytest.mark.asyncio
async def test_resolve_coerces_task_dag_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = build_default_agent_registry()
    cost = CostTracker()

    async def fake_llm_route(**kwargs: Any):
        return {
            "tasks": [
                {
                    "id": "task_1",
                    "type": "qa_kb",
                    "capabilities": ["kb_read"],
                    "depends_on": [],
                },
                {
                    "id": "task_2",
                    "type": "qa_chat",
                    "capabilities": ["chat", "web_search"],
                    "depends_on": ["task_1"],
                },
            ],
            "reason": "needs_kb_then_web",
            "source": kwargs["source"],
            "confidence": "high",
            "latency_ms": 9,
        }

    monkeypatch.setattr("src.runtime.router.llm_route", fake_llm_route)
    decision = await resolve_agent_route(
        has_kb=True,
        registry=reg,
        user_query="查知识库，不够再联网",
        cost=cost,
        triage_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="t"),
        complex_llm_cfg=SimpleNamespace(provider="openai-compat", default_model="c"),
        mode="layered",
    )
    assert decision["target"] == "rag"
    assert [t["agent"] for t in decision["tasks"]] == ["rag", "chat"]
    assert decision["tasks"][1]["depends_on"] == ["task_1"]
