"""Regression tests for the early chat quota boundary."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.streaming import session as streaming_session


async def test_chat_rate_limit_returns_remaining_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allowed(_key: str, _limit: int) -> tuple[bool, int]:
        return True, 7

    monkeypatch.setattr(streaming_session, "rate_check", allowed)

    assert await streaming_session.check_chat_rate_limit(
        rate_key="user:test", limit_per_hour=10
    ) == 7


async def test_chat_rate_limit_keeps_structured_retry_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def rejected(_key: str, _limit: int) -> tuple[bool, int]:
        return False, 0

    async def retry_after(_key: str) -> int:
        return 61

    monkeypatch.setattr(streaming_session, "rate_check", rejected)
    monkeypatch.setattr(streaming_session, "retry_after_seconds", retry_after)

    with pytest.raises(HTTPException) as exc_info:
        await streaming_session.check_chat_rate_limit(rate_key="user:test", limit_per_hour=10)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "61"
    assert exc_info.value.detail["code"] == "rate_limit_exceeded"
