"""Unit tests for the shared SQLite / memory rate limiter."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.infra import rate_limit
from src.settings import get_settings


@pytest.fixture(autouse=True)
def _clean_limiter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "sqlite")
    monkeypatch.setenv("RATE_LIMIT_DB_PATH", str(tmp_path / "rate_limit.db"))
    get_settings.cache_clear()
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()
    get_settings.cache_clear()


def test_rate_limit_allows_then_blocks() -> None:
    assert rate_limit.check("1.1.1.1", 2) == (True, 1)
    assert rate_limit.check("1.1.1.1", 2) == (True, 0)
    assert rate_limit.check("1.1.1.1", 2) == (False, 0)


def test_rate_limit_keys_are_isolated() -> None:
    assert rate_limit.check("a", 1)[0] is True
    assert rate_limit.check("b", 1)[0] is True
    assert rate_limit.check("a", 1)[0] is False


def test_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    get_settings.cache_clear()
    rate_limit.reset_for_tests()
    assert rate_limit.check("x", 1)[0] is True
    assert rate_limit.check("x", 1)[0] is False
