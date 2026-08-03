"""Per-conversation generation lock.

Prevents concurrent /api/chat streams for the same conversation_id within
one process. Multi-worker deployments need a shared store; for single-process
and typical docker compose this is sufficient.
"""
from __future__ import annotations

import asyncio

_guard = asyncio.Lock()
_active: set[str] = set()


async def try_acquire(conversation_id: str) -> bool:
    """Return True if this caller now owns the generation slot."""
    key = conversation_id.strip()
    if not key:
        return True
    async with _guard:
        if key in _active:
            return False
        _active.add(key)
        return True


async def release(conversation_id: str) -> None:
    key = conversation_id.strip()
    if not key:
        return
    async with _guard:
        _active.discard(key)


def reset_for_tests() -> None:
    """Clear all locks (tests only)."""
    _active.clear()
