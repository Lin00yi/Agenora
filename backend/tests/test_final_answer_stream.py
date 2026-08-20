"""Tests for final-answer / timeline streaming (Phase 3)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.runtime.agent_loop import reason_node
from src.models.gateway import CostTracker
from src.models.adapters import OpenAICompatToolAdapter, StreamHooks
from src.capabilities.settings.domain.models import UserLLMConfig
from src.tools.base import Tool, ToolRegistry, ToolResult


def _llm_cfg() -> UserLLMConfig:
    return UserLLMConfig(
        provider="openai-compat",
        api_key="sk-test",
        base_url="https://example.com/v1",
        default_model="gpt-test",
        complex_model="gpt-test",
        context_window=128000,
    )


class _DummyTool(Tool):
    name = "web_search"
    description = "web"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(text="ok", latency_ms=1)


@pytest.mark.asyncio
async def test_openai_stream_hooks_text_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            assert kwargs.get("stream") is True
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="hello world", tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    deltas: list[str] = []
    tools_hit = []

    async def on_text(t: str) -> None:
        deltas.append(t)

    async def on_tool() -> None:
        tools_hit.append(True)

    adapter = OpenAICompatToolAdapter(llm_cfg=_llm_cfg())
    resp = await adapter.chat_with_tools_stream(
        model="gpt-test",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_tokens=64,
        hooks=StreamHooks(on_text_delta=on_text, on_tool_detected=on_tool),
    )
    assert resp.text_parts == ["hello world"]
    assert resp.tool_calls == []
    assert deltas == ["hello world"]
    assert tools_hit == []


@pytest.mark.asyncio
async def test_openai_stream_hooks_tool_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tc = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="web_search", arguments='{"q":"x"}'),
    )

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(content=None, tool_calls=[tc]),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    deltas: list[str] = []
    tools_hit: list[bool] = []

    adapter = OpenAICompatToolAdapter(llm_cfg=_llm_cfg())
    resp = await adapter.chat_with_tools_stream(
        model="gpt-test",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "web_search", "description": "d", "input_schema": {}}],
        max_tokens=64,
        hooks=StreamHooks(
            on_text_delta=lambda t: deltas.append(t),
            on_tool_detected=lambda: tools_hit.append(True),
        ),
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "web_search"
    assert tools_hit == [True]
    assert deltas == []


@pytest.mark.asyncio
async def test_reason_node_streams_final_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="最终答案", tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    registry.register(_DummyTool())
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert next_state["final_report"] == "最终答案"
    assert next_state["report_streamed"] is True
    assert [e["event"] for e in events] == ["report_start", "token"]
    assert events[1]["text"] == "最终答案"


@pytest.mark.asyncio
async def test_reason_node_tools_do_not_stream_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tc = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="web_search", arguments="{}"),
    )

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(content=None, tool_calls=[tc]),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    registry.register(_DummyTool())
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert next_state.get("final_report") is None
    assert next_state.get("report_streamed") is False
    assert next_state["pending_tool_calls"]
    assert events == []


@pytest.mark.asyncio
async def test_reason_node_streams_text_then_seals_for_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tc = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="web_search", arguments="{}"),
    )

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="先查一下",
                            tool_calls=[tc],
                        ),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    registry.register(_DummyTool())
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert next_state.get("final_report") is None
    assert next_state.get("report_streamed") is False
    assert [e["event"] for e in events] == [
        "report_start",
        "token",
        "segment_seal",
    ]
    assert events[1]["text"] == "先查一下"


@pytest.mark.asyncio
async def test_reason_node_no_tools_streams_tokens_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="直接答", tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert next_state["final_report"] == "直接答"
    assert next_state["report_streamed"] is True
    assert [e["event"] for e in events] == ["report_start", "token"]
    assert events[1]["text"] == "直接答"


@pytest.mark.asyncio
async def test_reason_node_recovers_empty_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            calls["n"] += 1
            assert kwargs.get("tools") in (None, [])
            if calls["n"] == 1:
                content = None
            else:
                content = "恢复后的答案"
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=content, tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "四张卡的开卡规则？"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert calls["n"] == 2
    assert next_state["final_report"] == "恢复后的答案"
    assert next_state["report_streamed"] is True
    assert next_state["pending_tool_calls"] == []
    assert [e["event"] for e in events] == ["report_start", "token"]
    assert events[1]["text"] == "恢复后的答案"


@pytest.mark.asyncio
async def test_reason_node_empty_completion_falls_back_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime.agent_loop import EMPTY_ANSWER_FALLBACK

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=None, tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    registry = ToolRegistry()
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=_llm_cfg(),
        emit=emit,
    )
    assert next_state["final_report"] == EMPTY_ANSWER_FALLBACK
    assert next_state["report_streamed"] is False
    # Recovery also returned blank; no live tokens until app.py fake-chunks.
    assert events == []


@pytest.mark.asyncio
async def test_reason_node_escalates_to_complex_model_after_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            model = kwargs["model"]
            models.append(model)
            # Initial + same-model recovery stay empty; complex succeeds.
            content = "复杂模型给出的答案" if model == "gpt-complex" else None
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=content, tool_calls=None),
                    )
                ],
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("src.models.adapters.get_client", lambda cfg=None: fake_client)

    events: list[dict[str, Any]] = []

    async def emit(evt: dict[str, Any]) -> None:
        events.append(evt)

    cfg = UserLLMConfig(
        provider="openai-compat",
        api_key="sk-test",
        base_url="https://example.com/v1",
        default_model="gpt-test",
        complex_model="gpt-complex",
        context_window=128000,
    )
    registry = ToolRegistry()
    next_state = await reason_node(
        {"messages": [{"role": "user", "content": "q"}]},
        registry=registry,
        cost=CostTracker(),
        system_prompt="sys",
        llm_cfg=cfg,
        emit=emit,
    )
    assert models == ["gpt-test", "gpt-test", "gpt-complex"]
    assert next_state["final_report"] == "复杂模型给出的答案"
    assert next_state["report_streamed"] is True
    assert [e["event"] for e in events] == ["report_start", "token"]
    assert events[1]["text"] == "复杂模型给出的答案"
