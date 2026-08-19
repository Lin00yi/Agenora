from __future__ import annotations

import json
from typing import Any

import pytest

from src.settings_user.models import UserLLMConfig


@pytest.mark.asyncio
async def test_system_model_override_forces_default_and_complex(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import app as app_module

    captured: dict[str, UserLLMConfig | None] = {}

    class DummyGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"final_report": "ok", "cost_usd": 0.0}

    def fake_build_graph(**kwargs: Any) -> tuple[DummyGraph, Any]:
        captured["llm_cfg"] = kwargs["llm_cfg"]
        return DummyGraph(), object()

    monkeypatch.setattr(app_module, "rate_check", lambda *_args, **_kwargs: (True, 99))
    monkeypatch.setattr(app_module, "resolve_user_llm", lambda _user: None)
    monkeypatch.setattr(
        app_module,
        "resolve_system_llm",
        lambda: UserLLMConfig(
            provider="openai-compat",
            base_url="https://api.deepseek.com",
            api_key="test-key",
            default_model="deepseek-v4-flash",
            complex_model="deepseek-v4-pro",
            context_window=1_000_000,
        ),
    )
    monkeypatch.setattr(app_module, "build_supervisor_graph", fake_build_graph)
    monkeypatch.setattr(app_module, "build_graph", fake_build_graph)

    app_module._run_chat_session(
        [{"role": "user", "content": "hello"}],
        rate_key="test",
        model_override="deepseek-v4-pro",
    )

    assert captured["llm_cfg"] is not None
    assert captured["llm_cfg"].default_model == "deepseek-v4-pro"
    assert captured["llm_cfg"].complex_model == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_chat_stream_emits_safe_context_before_agent_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat timeline must receive its context entry before agent activity."""
    from src import app as app_module

    class DummyGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {"final_report": "ok", "cost_usd": 0.0}

    monkeypatch.setattr(app_module, "rate_check", lambda *_args, **_kwargs: (True, 99))
    monkeypatch.setattr(app_module, "resolve_user_llm", lambda _user: None)
    monkeypatch.setattr(
        app_module,
        "resolve_system_llm",
        lambda: UserLLMConfig(
            provider="openai-compat",
            base_url="https://api.deepseek.com",
            api_key="test-key",
            default_model="deepseek-v4-flash",
            complex_model="deepseek-v4-pro",
            context_window=1_000_000,
        ),
    )
    monkeypatch.setattr(
        app_module, "build_supervisor_graph", lambda **_kwargs: (DummyGraph(), object())
    )
    monkeypatch.setattr(app_module, "build_graph", lambda **_kwargs: (DummyGraph(), object()))

    response = app_module._run_chat_session(
        [{"role": "user", "content": "hello"}],
        rate_key="test",
        memory_trace={"recent_message_count": 1},
    )
    events = [json.loads(packet["data"]) async for packet in response.body_iterator]

    assert events[0] == {
        "event": "context_ready",
        "memory_trace": {
            "recent_message_count": 1,
            "runtime": {
                "mode": "general",
                "agent_runtime": "supervisor",
                "safety": "standard",
            },
        },
    }
    assert events[1]["event"] == "report_start"
    assert "prompt" not in events[0]["memory_trace"]
    assert "credentials" not in events[0]["memory_trace"]
