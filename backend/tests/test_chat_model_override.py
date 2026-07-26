from __future__ import annotations

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
    monkeypatch.setattr(app_module, "build_graph", fake_build_graph)

    app_module._run_chat_session(
        [{"role": "user", "content": "hello"}],
        rate_key="test",
        model_override="deepseek-v4-pro",
    )

    assert captured["llm_cfg"] is not None
    assert captured["llm_cfg"].default_model == "deepseek-v4-pro"
    assert captured["llm_cfg"].complex_model == "deepseek-v4-pro"
