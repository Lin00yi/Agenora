"""Topology-safe per-key sliding-window rate limiting.

``postgres`` is the production backend. Each decision runs in one database
transaction protected by a transaction advisory lock, so all API replicas
share a single source of truth. SQLite and memory remain intentionally local
development fallbacks; neither is selected automatically for PostgreSQL.
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from math import ceil
from pathlib import Path
from threading import Lock
from typing import Literal

from sqlalchemy import text

from src.platform.persistence.database import get_session_factory
from src.settings import get_settings

RateLimitBackend = Literal["postgres", "sqlite", "memory"]

_memory_buckets: dict[str, list[float]] = {}
_memory_lock = Lock()
_db_lock = Lock()
_db_path: Path | None = None
_WINDOW_SECONDS = 3600.0


def resolve_backend() -> RateLimitBackend:
    """Resolve ``auto`` safely from the configured application database."""
    settings = get_settings()
    requested = str(getattr(settings, "rate_limit_backend", "auto") or "auto").strip().lower()
    if requested in {"postgres", "sqlite", "memory"}:
        return requested  # type: ignore[return-value]
    return "postgres" if str(settings.database_url).startswith("postgresql") else "sqlite"


def _advisory_key(rate_key: str) -> int:
    digest = hashlib.sha256(rate_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _resolve_db_path() -> Path:
    global _db_path
    if _db_path is None:
        settings = get_settings()
        configured = getattr(settings, "rate_limit_db_path", "") or ""
        if configured:
            path = Path(configured)
        else:
            path = Path(__file__).resolve().parents[2] / "data" / "rate_limit.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _db_path = path
    return _db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_resolve_db_path()), timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hits (
            rate_key TEXT NOT NULL,
            ts REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hits_key_ts ON hits (rate_key, ts)")
    return conn


def _check_sqlite(rate_key: str, limit_per_hour: int) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - _WINDOW_SECONDS
    with _db_lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM hits WHERE rate_key = ? AND ts <= ?", (rate_key, cutoff))
            row = conn.execute(
                "SELECT COUNT(*) FROM hits WHERE rate_key = ? AND ts > ?", (rate_key, cutoff)
            ).fetchone()
            count = int(row[0] if row else 0)
            if count >= limit_per_hour:
                return False, 0
            conn.execute("INSERT INTO hits (rate_key, ts) VALUES (?, ?)", (rate_key, now))
            return True, limit_per_hour - count - 1
        finally:
            conn.close()


def _check_memory(rate_key: str, limit_per_hour: int) -> tuple[bool, int]:
    now = time.time()
    with _memory_lock:
        active = [ts for ts in _memory_buckets.get(rate_key, []) if now - ts <= _WINDOW_SECONDS]
        if len(active) >= limit_per_hour:
            _memory_buckets[rate_key] = active
            return False, 0
        active.append(now)
        _memory_buckets[rate_key] = active
        return True, limit_per_hour - len(active)


async def _check_postgres(rate_key: str, limit_per_hour: int) -> tuple[bool, int]:
    """Atomically prune, count and record a request across every API replica."""
    now = time.time()
    cutoff = now - _WINDOW_SECONDS
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _advisory_key(rate_key)},
            )
            await session.execute(
                text("DELETE FROM rate_limit_hits WHERE rate_key = :rate_key AND ts <= :cutoff"),
                {"rate_key": rate_key, "cutoff": cutoff},
            )
            count = int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM rate_limit_hits WHERE rate_key = :rate_key"),
                        {"rate_key": rate_key},
                    )
                ).scalar_one()
            )
            if count >= limit_per_hour:
                return False, 0
            await session.execute(
                text("INSERT INTO rate_limit_hits (rate_key, ts) VALUES (:rate_key, :ts)"),
                {"rate_key": rate_key, "ts": now},
            )
            return True, limit_per_hour - count - 1


async def check(rate_key: str, limit_per_hour: int) -> tuple[bool, int]:
    """Return ``(allowed, remaining)`` using the resolved shared backend."""
    backend = resolve_backend()
    if backend == "postgres":
        return await _check_postgres(rate_key, limit_per_hour)
    if backend == "memory":
        return _check_memory(rate_key, limit_per_hour)
    try:
        return await asyncio.to_thread(_check_sqlite, rate_key, limit_per_hour)
    except Exception:  # noqa: BLE001 - local dev should remain available
        return _check_memory(rate_key, limit_per_hour)


def _retry_after_memory(rate_key: str) -> int:
    now = time.time()
    with _memory_lock:
        active = [ts for ts in _memory_buckets.get(rate_key, []) if now - ts <= _WINDOW_SECONDS]
        if not active:
            return 1
        return max(1, int(ceil(active[0] + _WINDOW_SECONDS - now)))


def _retry_after_sqlite(rate_key: str) -> int:
    now = time.time()
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT MIN(ts) FROM hits WHERE rate_key = ? AND ts > ?",
                (rate_key, now - _WINDOW_SECONDS),
            ).fetchone()
        finally:
            conn.close()
    oldest = row[0] if row else None
    if not isinstance(oldest, (int, float)):
        return 1
    return max(1, int(ceil(float(oldest) + _WINDOW_SECONDS - now)))


async def _retry_after_postgres(rate_key: str) -> int:
    now = time.time()
    factory = get_session_factory()
    async with factory() as session:
        oldest = (
            await session.execute(
                text(
                    "SELECT MIN(ts) FROM rate_limit_hits "
                    "WHERE rate_key = :rate_key AND ts > :cutoff"
                ),
                {"rate_key": rate_key, "cutoff": now - _WINDOW_SECONDS},
            )
        ).scalar_one()
    if not isinstance(oldest, (int, float)):
        return 1
    return max(1, int(ceil(float(oldest) + _WINDOW_SECONDS - now)))


async def retry_after_seconds(rate_key: str) -> int:
    """Return the earliest safe retry delay for a currently limited key."""
    backend = resolve_backend()
    if backend == "postgres":
        return await _retry_after_postgres(rate_key)
    if backend == "memory":
        return _retry_after_memory(rate_key)
    try:
        return await asyncio.to_thread(_retry_after_sqlite, rate_key)
    except Exception:  # noqa: BLE001
        return _retry_after_memory(rate_key)


def reset_for_tests() -> None:
    """Clear only local backend state (PostgreSQL state belongs to its fixture)."""
    global _db_path
    with _memory_lock:
        _memory_buckets.clear()
    with _db_lock:
        path = _db_path
        _db_path = None
    if path and path.exists():
        path.unlink(missing_ok=True)
