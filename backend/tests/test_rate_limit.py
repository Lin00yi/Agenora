from __future__ import annotations

from types import SimpleNamespace

from src.platform.runtime import rate_limit


def test_rate_limit_exposes_a_positive_retry_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(rate_limit_backend="memory"),
    )
    rate_limit.reset_for_tests()

    assert rate_limit.check("user:test", 1) == (True, 0)
    assert rate_limit.check("user:test", 1) == (False, 0)
    assert 1 <= rate_limit.retry_after_seconds("user:test") <= 3600
