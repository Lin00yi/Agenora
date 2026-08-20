"""Per-conversation generation lock.

SQLite/local development uses a process-local lock. PostgreSQL deployments use
a session-level advisory lock held by a dedicated connection for the lifetime
of the SSE stream, so separate API workers cannot generate into the same
conversation concurrently. PostgreSQL releases the lock if a worker dies.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

_guard = asyncio.Lock()
_active: set[str] = set()
_postgres_connections: dict[str, Any] = {}


def _uses_postgres() -> bool:
    from src.settings import get_settings

    return get_settings().database_url.startswith("postgresql")


def _advisory_key(conversation_id: str) -> int:
    """Return a stable signed bigint accepted by PostgreSQL advisory locks."""
    digest = hashlib.sha256(conversation_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def try_acquire(conversation_id: str) -> bool:
    """Return True if this caller now owns the generation slot."""
    key = conversation_id.strip()
    if not key:
        return True
    async with _guard:
        if key in _active:
            return False
        if _uses_postgres():
            from sqlalchemy import text

            from src.platform.persistence.database import get_engine

            connection = await get_engine().connect()
            try:
                acquired = bool(
                    (
                        await connection.execute(
                            text("SELECT pg_try_advisory_lock(:lock_key)"),
                            {"lock_key": _advisory_key(key)},
                        )
                    ).scalar()
                )
                if not acquired:
                    await connection.close()
                    return False
            except Exception:
                await connection.close()
                raise
            _postgres_connections[key] = connection
        _active.add(key)
        return True


async def release(conversation_id: str) -> None:
    key = conversation_id.strip()
    if not key:
        return
    async with _guard:
        _active.discard(key)
        connection = _postgres_connections.pop(key, None)
        if connection is None:
            return
        try:
            from sqlalchemy import text

            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _advisory_key(key)},
            )
        finally:
            await connection.close()


def reset_for_tests() -> None:
    """Clear all locks (tests only)."""
    _active.clear()
    _postgres_connections.clear()
