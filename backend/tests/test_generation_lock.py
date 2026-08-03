"""Unit tests for per-conversation generation lock."""
from __future__ import annotations

import asyncio

import pytest

from src.infra import generation_lock


@pytest.fixture(autouse=True)
def _reset_locks():
    generation_lock.reset_for_tests()
    yield
    generation_lock.reset_for_tests()


@pytest.mark.asyncio
async def test_generation_lock_rejects_second_acquire() -> None:
    assert await generation_lock.try_acquire("conv-a") is True
    assert await generation_lock.try_acquire("conv-a") is False
    assert await generation_lock.try_acquire("conv-b") is True
    await generation_lock.release("conv-a")
    assert await generation_lock.try_acquire("conv-a") is True


@pytest.mark.asyncio
async def test_generation_lock_concurrent_contenders() -> None:
    async def contender() -> bool:
        return await generation_lock.try_acquire("shared")

    results = await asyncio.gather(*[contender() for _ in range(20)])
    assert sum(1 for ok in results if ok) == 1
