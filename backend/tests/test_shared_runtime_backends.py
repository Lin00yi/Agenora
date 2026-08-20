from __future__ import annotations

from types import SimpleNamespace

from src.harness.runtime.checkpoints import checkpoint_postgres_url, resolve_checkpoint_backend
from src.platform.runtime.rate_limit import resolve_backend


def test_postgres_runtime_backends_are_selected_for_a_postgres_app_database(monkeypatch) -> None:
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:secret@db:5432/agenora",
        agent_checkpoint_backend="auto",
        agent_checkpoint_database_url="",
        rate_limit_backend="auto",
    )
    assert resolve_checkpoint_backend(settings) == "postgres"
    assert checkpoint_postgres_url(settings) == "postgresql://user:secret@db:5432/agenora"

    monkeypatch.setattr("src.platform.runtime.rate_limit.get_settings", lambda: settings)
    assert resolve_backend() == "postgres"


def test_local_runtime_backends_keep_sqlite_without_a_postgres_database(monkeypatch) -> None:
    settings = SimpleNamespace(
        database_url="sqlite+aiosqlite:////tmp/agenora.db",
        agent_checkpoint_backend="auto",
        agent_checkpoint_database_url="",
        rate_limit_backend="auto",
    )
    assert resolve_checkpoint_backend(settings) == "sqlite"
    monkeypatch.setattr("src.platform.runtime.rate_limit.get_settings", lambda: settings)
    assert resolve_backend() == "sqlite"
