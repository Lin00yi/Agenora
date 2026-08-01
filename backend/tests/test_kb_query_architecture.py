from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.nodes import (
    kb_search_node,
    query_policy_node,
    query_rewrite_node,
    reason_node,
    should_search_kb,
)
from src.agent.graph import build_graph
from src.infra.llm import CostTracker
from src.settings_user.models import UserLLMConfig
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


def test_user_kb_graph_compiles_with_rewrite_and_search_nodes() -> None:
    registry = ToolRegistry()
    registry.register(RecordingKBSearchTool())
    kb = SimpleNamespace(
        id="user-kb-id",
        name="AnyKB",
        description="AnyKB product docs",
        is_system=False,
    )

    graph, cost = build_graph(registry=registry, kb=kb, llm_cfg=_llm_cfg())

    assert graph is not None
    assert cost is not None
    assert hasattr(graph, "ainvoke")


@pytest.mark.asyncio
async def test_query_policy_direct_rule_does_not_call_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy_env(monkeypatch, KB_QUERY_POLICY_MODE="llm_fallback")

    def fail_client(cfg: Any = None) -> Any:  # noqa: ARG001
        raise AssertionError("LLM policy should not be called for clear direct queries")

    monkeypatch.setattr("src.agent.nodes.get_client", fail_client)

    state = {"messages": [{"role": "user", "content": "AnyKB 支持私有化吗？"}]}
    next_state = await query_policy_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["query_policy_action"] == "direct"
    assert next_state["query_policy_source"] == "rule"
    assert next_state["kb_queries"] == [{"query": "AnyKB 支持私有化吗？", "limit": 5}]
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
                                '{"query":"AnyKB 数据安全","limit":5},'
                                '{"query":"AnyKB 本地部署 私有化","limit":5},'
                                '{"query":"AnyKB 数据加密 隐私","limit":5},'
                                '{"query":"AnyKB 企业版","limit":5}'
                                "]}"
                            )
                        )
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.agent.nodes.get_client", lambda cfg=None: fake_client)

    state = {
        "messages": [
            {
                "role": "user",
                "content": "AnyKB 如何保证数据安全？是否支持本地部署和私有化？",
            }
        ]
    }
    next_state = await query_policy_node(
        state,
        cost=CostTracker(),
        kb_name="AnyKB",
        llm_cfg=_llm_cfg(),
    )

    assert len(calls) == 1
    assert next_state["query_policy_action"] == "expand"
    assert next_state["query_policy_source"] == "llm"
    assert next_state["query_policy_reason"] == "multi_intent"
    assert [item["query"] for item in next_state["kb_queries"]] == [
        "AnyKB 数据安全",
        "AnyKB 本地部署 私有化",
        "AnyKB 数据加密 隐私",
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
    monkeypatch.setattr("src.agent.nodes.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "AnyKB 支持私有化吗？"}]}
    await query_policy_node(state, cost=CostTracker(), llm_cfg=_anthropic_llm_cfg())

    assert captured_models == ["claude-haiku-4-5-20251001"]


@pytest.mark.asyncio
async def test_query_rewrite_node_caps_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"queries":['
                                '{"query":"AnyKB 数据安全","limit":5},'
                                '{"query":"AnyKB 本地部署 私有化","limit":5},'
                                '{"query":"AnyKB 数据加密 隐私","limit":5},'
                                '{"query":"AnyKB 企业版","limit":5}'
                                "]}"
                            )
                        )
                    )
                ],
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr("src.agent.nodes.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "AnyKB 如何保证数据安全？"}]}
    next_state = await query_rewrite_node(
        state,
        cost=CostTracker(),
        kb_name="AnyKB",
        llm_cfg=_llm_cfg(),
    )

    assert [item["query"] for item in next_state["kb_queries"]] == [
        "AnyKB 数据安全",
        "AnyKB 本地部署 私有化",
        "AnyKB 数据加密 隐私",
    ]
    assert next_state["kb_search_done"] is False


@pytest.mark.asyncio
async def test_query_rewrite_node_falls_back_to_user_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            raise RuntimeError("llm unavailable")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr("src.agent.nodes.get_client", lambda cfg=None: fake_client)

    state = {"messages": [{"role": "user", "content": "AnyKB 支持私有化吗？"}]}
    next_state = await query_rewrite_node(state, cost=CostTracker(), llm_cfg=_llm_cfg())

    assert next_state["kb_queries"] == [
        {"query": "AnyKB 支持私有化吗？", "limit": 5}
    ]


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
    assert "KB search query: q1" in next_state["kb_context"]
    assert "hit for q3" in next_state["kb_context"]
    assert next_state["kb_search_done"] is True
    assert [evt["event"] for evt in events].count("tool_start") == 3
    assert [evt["event"] for evt in events].count("tool_end") == 3
    assert len(next_state["tool_call_log"]) == 3


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
    monkeypatch.setattr("src.infra.llm_adapters.get_client", lambda cfg=None: fake_client)

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
        include_travel_skill=False,
        excluded_tool_names={"search_kb"},
        llm_cfg=_llm_cfg(),
    )

    assert captured_tools == ["web_search"]
    assert next_state["final_report"] == "answer"
