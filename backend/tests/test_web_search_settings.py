"""Regression coverage for user-configurable web-search engines."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.capabilities.settings.application import kb_options
from src.capabilities.settings.domain.models import UserWebSearchConfig, resolve_user_web_search
from src.harness.tools import search_providers
from src.harness.tools.search_providers import SearchResult
from src.harness.tools.web_search import WebSearchTool


class _Session:
    async def commit(self) -> None:
        return None

    async def refresh(self, _user: object) -> None:
        return None


@pytest.mark.asyncio
async def test_save_web_search_keeps_paid_key_and_clears_it_for_duckduckgo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kb_options, "encrypt", lambda value: f"encrypted:{value}")
    user = SimpleNamespace(web_search_provider=None, web_search_api_key_enc=None)
    session = _Session()

    await kb_options.save_web_search(
        session,
        user=user,
        body=SimpleNamespace(provider="brave", api_key="brave-key"),
    )
    assert user.web_search_provider == "brave"
    assert user.web_search_api_key_enc == "encrypted:brave-key"

    with pytest.raises(kb_options.KBOptionsUseCaseError):
        await kb_options.save_web_search(
            session,
            user=user,
            body=SimpleNamespace(provider="bing", api_key=""),
        )
    assert user.web_search_provider == "brave"

    await kb_options.save_web_search(
        session,
        user=user,
        body=SimpleNamespace(provider="duckduckgo", api_key=""),
    )
    assert user.web_search_provider == "duckduckgo"
    assert user.web_search_api_key_enc is None


def test_resolve_user_web_search_returns_none_without_an_override() -> None:
    assert resolve_user_web_search(SimpleNamespace(web_search_provider=None)) is None


def test_explicit_search_config_overrides_the_env_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_providers,
        "get_settings",
        lambda: SimpleNamespace(
            web_search_provider="duckduckgo",
            brave_search_api_key="env-key",
            bing_search_api_key="",
            tavily_api_key="",
        ),
    )
    provider = search_providers.get_search_provider(
        UserWebSearchConfig(provider="brave", api_key="user-key")
    )
    assert provider.name == "brave"
    assert provider.api_key == "user-key"


@pytest.mark.asyncio
async def test_web_search_tool_passes_the_user_config_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = UserWebSearchConfig(provider="tavily", api_key="user-key")
    seen: list[UserWebSearchConfig | None] = []

    class _Provider:
        name = "tavily"

        async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
            assert query == "Agenora"
            assert max_results == 2
            return [SearchResult(title="Agenora", url="https://example.com", body="Agenora docs")]

    def provider_factory(value: UserWebSearchConfig | None) -> _Provider:
        seen.append(value)
        return _Provider()

    monkeypatch.setattr("src.harness.tools.web_search.get_search_provider", provider_factory)
    result = await WebSearchTool(
        max_results_default=2,
        max_results_cap=2,
        search_config=config,
    ).execute("Agenora")

    assert result.error is None
    assert result.raw["provider"] == "tavily"
    assert seen == [config]
