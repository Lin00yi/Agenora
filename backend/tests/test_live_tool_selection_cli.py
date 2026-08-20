"""Credential-source coverage for the opt-in live evaluation CLI."""
from __future__ import annotations

import pytest

from src.capabilities.settings.domain.models import UserLLMConfig
from src.harness.evaluation import live_tool_selection_cli as cli
from src.harness.evaluation.live_tool_selection import LiveToolSelectionError


def _cfg() -> UserLLMConfig:
    return UserLLMConfig(
        provider="openai-compat",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        default_model="test-model",
        complex_model="test-model",
        context_window=16_000,
    )


async def test_live_cli_uses_system_config_without_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _cfg()
    monkeypatch.setattr(cli, "resolve_system_llm", lambda: expected)

    assert await cli._resolve_baseline_llm() is expected


async def test_live_cli_requires_explicitly_configured_user(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session:
        async def get(self, _model, _user_id):
            return object()

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, _type, _value, _traceback):
            return None

    class Factory:
        def __call__(self):
            return SessionContext()

    expected = _cfg()
    monkeypatch.setattr(cli, "get_session_factory", lambda: Factory())
    monkeypatch.setattr(cli, "resolve_user_llm", lambda _user: expected)

    assert await cli._resolve_baseline_llm(user_id="user-1") is expected


async def test_live_cli_does_not_fallback_from_requested_user_to_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        async def get(self, _model, _user_id):
            return None

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, _type, _value, _traceback):
            return None

    class Factory:
        def __call__(self):
            return SessionContext()

    monkeypatch.setattr(cli, "get_session_factory", lambda: Factory())
    monkeypatch.setattr(cli, "resolve_system_llm", lambda: _cfg())

    with pytest.raises(LiveToolSelectionError, match="was not found"):
        await cli._resolve_baseline_llm(user_id="missing-user")
