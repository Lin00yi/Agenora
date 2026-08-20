from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.runtime.agent_loop import (
    kb_search_node,
    query_policy_node,
    reason_node,
    should_search_kb,
)
from src.runtime.agent_loop.kb_search import _bound_aggregated_rag_context
from src.context import RAG_RESERVE, estimate_tokens
from src.models.gateway import CostTracker
from src.capabilities.settings.domain.models import UserLLMConfig
from src.tools.base import Tool, ToolRegistry, ToolResult


class RecordingKBSearchTool(Tool):
    name = "search_kb"
    description = "test KB search"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        query = kwargs.get("query", "")
        return ToolResult(text=f"hit for {query}", latency_ms=1)


class DummyWebTool(Tool):
    name = "web_search"
    description = "test web search"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        return ToolResult(text="web hit", latency_ms=1)


def test_aggregated_kb_and_kg_context_has_one_turn_cap() -> None:
    merged = _bound_aggregated_rag_context(
        ["KB-1\n" + "证据" * 5_000, "KB-2\n" + "证据" * 5_000, "KG\n" + "关系" * 5_000]
    )

    assert estimate_tokens(merged) <= RAG_RESERVE
    assert "KB-1" in merged
    assert "其余检索内容因本轮 RAG 预算省略" in merged


def _llm_cfg() -> UserLLMConfig:
    return UserLLMConfig(
        provider="openai-compat",
        base_url="http://llm.test/v1",
        api_key="test",
        default_model="deepseek-v4-flash",
        complex_model="deepseek-v4-pro",
        context_window=1_000_000,
    )


def _anthropic_llm_cfg() -> UserLLMConfig:
    return UserLLMConfig(
        provider="anthropic",
        base_url="http://anthropic.test",
        api_key="test",
        default_model="claude-haiku-4-5-20251001",
        complex_model="claude-sonnet-4-6",
        context_window=200_000,
    )


def _set_policy_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    from src.settings import get_settings

    defaults = {
        "KB_QUERY_POLICY_MODE": "llm_fallback",
        "KB_QUERY_POLICY_MAX_QUERIES": "3",
        "KB_QUERY_POLICY_LLM_MODEL": "",
    }
    defaults.update(values)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_query_policy_direct_rule_does_not_call_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")

    def fail_client(cfg: Any = None) -> Any:  # noqa: ARG001
        raise AssertionError("LLM policy should not be called for clear direct queries")

    monkeypatch.setattr("src.runtime.agent_loop.get_client", fail_client)

    state = {"messages": [{"role": "user", "content": "Agenora 支持私有化吗？"}]}
    next_state = await query_policy_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["query_policy_action"] == "direct"
    assert next_state["query_policy_source"] == "rule"
    assert next_state["kb_queries"] == [{"query": "Agenora 支持私有化吗？", "limit": 3}]
    assert next_state["kb_search_done"] is False


@pytest.mark.asyncio
async def test_query_policy_complex_query_uses_llm_and_caps_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")
    calls: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"action":"expand","reason":"multi_intent","queries":['
                                '{"query":"Agenora 数据安全","limit":5},'
                                '{"query":"Agenora 本地部署 私有化","limit":5},'
                                '{"query":"Agenora 数据加密 隐私","limit":5},'
                                '{"query":"Agenora 企业版","limit":5}'
                                "]}"
                            )
                        )
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.runtime.agent_loop.get_client", lambda cfg=None: fake_client)

    state = {
        "messages": [
            {
                "role": "user",
                "content": "Agenora 如何保证数据安全？是否支持本地部署和私有化？",
            }
        ]
    }
    next_state = await query_policy_node(
        state,
        cost=CostTracker(),
        kb_name="Agenora",
        llm_cfg=_llm_cfg(),
    )

    assert len(calls) == 1
    assert next_state["query_policy_action"] == "expand"
    assert next_state["query_policy_source"] == "llm"
    assert next_state["query_policy_reason"] == "multi_intent"
    assert [item["query"] for item in next_state["kb_queries"]] == [
        "Agenora 数据安全",
        "Agenora 本地部署 私有化",
        "Agenora 数据加密 隐私",
    ]


@pytest.mark.asyncio
async def test_query_policy_skip_kb_routes_to_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")

    state = {"messages": [{"role": "user", "content": "总结刚才的回答"}]}
    next_state = await query_policy_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["query_policy_action"] == "skip_kb"
    assert next_state["query_policy_source"] == "rule"
    assert next_state["kb_queries"] == []
    assert next_state["kb_search_done"] is True
    assert should_search_kb(next_state) == "reason"


@pytest.mark.asyncio
async def test_query_policy_model_override_respects_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(
        monkeypatch,
        KB_QUERY_POLICY_MODE="always_llm",
        KB_QUERY_POLICY_LLM_MODEL="deepseek-v4-flash",
    )
    captured_models: list[str] = []

    class FakeMessages:
        async def create(self, **kwargs: Any) -> Any:
            captured_models.append(kwargs["model"])
            return SimpleNamespace(
                usage=None,
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"action":"direct","queries":[{"query":"q","limit":5}],"reason":"ok"}',
                    )
                ],
            )

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr("src.runtime.agent_loop.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "Agenora 支持私有化吗？"}]}
    await query_policy_node(state, cost=CostTracker(), llm_cfg=_anthropic_llm_cfg())

    assert captured_models == ["claude-haiku-4-5-20251001"]


@pytest.mark.asyncio
async def test_kb_search_node_runs_rewritten_queries_in_parallel() -> None:
    tool = RecordingKBSearchTool(delay=0.05)
    registry = ToolRegistry()
    registry.register(tool)
    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    state = {
        "kb_queries": [
            {"query": "q1", "limit": 5},
            {"query": "q2", "limit": 5},
            {"query": "q3", "limit": 5},
        ],
        "tool_call_log": [],
    }

    start = time.perf_counter()
    next_state = await kb_search_node(state, registry=registry, emit=emit)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.12
    assert [call["query"] for call in tool.calls] == ["q1", "q2", "q3"]
    assert next_state["kb_context"] == ""
    assert len(next_state["retrieved_evidence"]) == 3
    assert next_state["retrieved_evidence"][0]["source_type"] == "kb"
    assert next_state["retrieved_evidence"][0]["query"] == "q1"
    assert next_state["kb_search_done"] is True
    assert [evt["event"] for evt in events].count("tool_start") == 3
    assert [evt["event"] for evt in events].count("tool_end") == 3
    assert len(next_state["tool_call_log"]) == 3


class SlowKGSearchTool(Tool):
    name = "search_kg"
    description = "slow KG search"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, *, delay: float = 0.5) -> None:
        self.delay = delay
        self.calls = 0

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        self.calls += 1
        await asyncio.sleep(self.delay)
        return ToolResult(text="kg hit", latency_ms=int(self.delay * 1000))


class StrongKBSearchTool(Tool):
    name = "search_kb"
    description = "strong KB hit"
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        return ToolResult(
            text=f"hit for {query}",
            latency_ms=5,
            raw={"hits": 1, "results": [{"filename": "a.md", "score": 0.91}]},
        )


@pytest.mark.asyncio
async def test_kb_search_node_skips_kg_for_listing_when_kb_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.settings import get_settings

    monkeypatch.setenv("LIGHTRAG_KG_ONLY_WHEN_NEEDED", "true")
    monkeypatch.setenv("LIGHTRAG_KG_SOFT_WAIT_S", "0")
    get_settings.cache_clear()

    kb = StrongKBSearchTool()
    kg = SlowKGSearchTool(delay=0.4)
    registry = ToolRegistry()
    registry.register(kb)
    registry.register(kg)
    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    state = {
        "kb_queries": [{"query": "目前有哪些卡片", "limit": 5}],
        "tool_call_log": [],
    }
    start = time.perf_counter()
    next_state = await kb_search_node(state, registry=registry, emit=emit)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2
    assert next_state["kb_search_done"] is True
    assert next_state["kb_context"] == ""
    assert kg.calls == 0
    assert not any(e.get("name") == "search_kg" for e in events)


def test_rule_query_policy_defers_multi_intent_to_llm() -> None:
    from src.runtime.agent_loop import _rule_query_policy

    # Multi-intent / multi-clause should return None so query_policy LLM can decide.
    assert _rule_query_policy("目前有哪些卡片，以及卡组涉及哪些？", max_queries=2) is None


def test_rule_query_policy_defers_ambiguous_abuse_to_semantic_classifier() -> None:
    from src.runtime.agent_loop import _rule_query_policy

    decision = _rule_query_policy("去死吧 Roogoo", max_queries=2)

    assert decision is None


@pytest.mark.asyncio
async def test_query_policy_semantically_skips_non_informational_abuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            assert "情绪表达、抱怨或攻击性话语" in kwargs["messages"][0]["content"]
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"skip_kb","queries":[],"reason":"non_informational"}'
                        )
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.runtime.agent_loop.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "去死吧 Roogoo"}]}
    next_state = await query_policy_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["query_policy_action"] == "skip_kb"
    assert next_state["query_policy_source"] == "llm"
    assert next_state["kb_queries"] == []


@pytest.mark.asyncio
async def test_query_policy_fails_closed_for_ambiguous_abuse_when_classifier_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")

    class FailingCompletions:
        async def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            raise RuntimeError("classifier unavailable")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    monkeypatch.setattr("src.runtime.agent_loop.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "去死吧 Roogoo"}]}
    next_state = await query_policy_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["query_policy_action"] == "skip_kb"
    assert next_state["query_policy_source"] == "fallback"
    assert next_state["query_policy_reason"] == "semantic_non_kb_classification_failed"


@pytest.mark.asyncio
async def test_reason_node_can_hide_search_kb_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_tools: list[str] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            captured_tools.extend(
                tool["function"]["name"] for tool in (kwargs.get("tools") or [])
            )
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=None))
                ],
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    registry = ToolRegistry()
    registry.register(RecordingKBSearchTool())
    registry.register(DummyWebTool())

    state = {
        "messages": [{"role": "user", "content": "question"}],
        "kb_context": "## KB search query: question\nhit",
    }
    next_state = await reason_node(
        state,
        registry=registry,
        cost=CostTracker(),
        system_prompt="answer from KB",
        excluded_tool_names={"search_kb"},
        llm_cfg=_llm_cfg(),
    )

    assert captured_tools == ["web_search"]
    assert next_state["final_report"] == "answer"


@pytest.mark.asyncio
async def test_reason_node_auto_continues_truncated_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    usage=None,
                    choices=[
                        SimpleNamespace(
                            finish_reason="length",
                            message=SimpleNamespace(content="第一段", tool_calls=None),
                        )
                    ],
                )
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="第二段", tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "请输出完整报告"}]},
        registry=ToolRegistry(),
        cost=CostTracker(),
        system_prompt="answer fully",
        llm_cfg=_llm_cfg(),
    )

    assert next_state["final_report"] == "第一段\n\n第二段"
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 8_192
    assert "从断点继续" in calls[1]["messages"][-1]["content"]
