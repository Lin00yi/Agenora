"""HTTP contract tests for web-search settings persistence."""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import settings as settings_routes
from src.capabilities.identity.middleware import current_user
from src.capabilities.identity.models import User
from src.capabilities.settings.application import kb_options


class _Session:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get(self, model: type[User], key: str) -> User | None:
        return self.user if model is User and key == self.user.id else None

    async def commit(self) -> None:
        return None

    async def refresh(self, _user: User) -> None:
        return None


def _client(user: User) -> TestClient:
    app = FastAPI()
    app.include_router(settings_routes.router)
    session = _Session(user)

    async def current() -> User:
        return user

    async def get_session() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[current_user] = current
    app.dependency_overrides[settings_routes.get_session] = get_session
    return TestClient(app)


def test_web_search_route_saves_only_after_successful_verification(monkeypatch) -> None:
    user = User(id="user-1", email="user@example.com", password_hash="!")

    async def verified(**_kwargs: object) -> int:
        return 1

    monkeypatch.setattr(kb_options, "verify_web_search", verified)
    monkeypatch.setattr(kb_options, "encrypt", lambda value: f"encrypted:{value}")

    with _client(user) as client:
        response = client.put(
            "/api/settings/web-search",
            json={"provider": "brave", "api_key": "new-key"},
        )

    assert response.status_code == 200
    assert response.json()["web_search"]["provider"] == "brave"
    assert user.web_search_provider == "brave"
    assert user.web_search_api_key_enc == "encrypted:new-key"


def test_web_search_route_rejects_failed_verification_without_mutating_user(monkeypatch) -> None:
    user = User(id="user-1", email="user@example.com", password_hash="!")
    user.web_search_provider = "brave"
    user.web_search_api_key_enc = "old-key"

    async def rejected(**_kwargs: object) -> int:
        raise kb_options.KBOptionsUseCaseError(
            {
                "code": "search_provider_auth_failed",
                "message": "API Key 无效，或当前账号没有搜索权限。",
            },
            502,
        )

    monkeypatch.setattr(kb_options, "verify_web_search", rejected)

    with _client(user) as client:
        response = client.put(
            "/api/settings/web-search",
            json={"provider": "tavily", "api_key": "invalid-key"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "search_provider_auth_failed",
        "message": "API Key 无效，或当前账号没有搜索权限。",
    }
    assert user.web_search_provider == "brave"
    assert user.web_search_api_key_enc == "old-key"


def test_restore_default_rejects_unavailable_system_engine_without_mutation(monkeypatch) -> None:
    user = User(id="user-1", email="user@example.com", password_hash="!")
    user.web_search_provider = "brave"
    user.web_search_api_key_enc = "old-key"

    async def unavailable() -> int:
        raise kb_options.KBOptionsUseCaseError(
            {
                "code": "system_search_provider_unavailable",
                "message": "系统默认搜索引擎不可用，暂不能恢复默认配置。",
            },
            502,
        )

    monkeypatch.setattr(kb_options, "verify_system_web_search", unavailable)

    with _client(user) as client:
        response = client.delete("/api/settings/web-search")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "system_search_provider_unavailable"
    assert user.web_search_provider == "brave"
    assert user.web_search_api_key_enc == "old-key"
