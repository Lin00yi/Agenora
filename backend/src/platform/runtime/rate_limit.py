"""Shared SQLite rate limiter — safe across multiple workers on one host.

Uses a dedicated SQLite file (WAL) so uvicorn multi-worker / multi-process
deployments share the same counters. Multi-host replicas still need an
external limiter (Redis / nginx) — set RATE_LIMIT_BACKEND=memory only for
single-process local demos if desired.
"""
from __future__ import annotations

import sqlite3
import time
from math import ceil
from pathlib import Path
from threading import Lock

from src.settings import get_settings

_memory_buckets: dict[str, list[float]] = {}
_memory_lock = Lock()
_db_lock = Lock()
_db_path: Path | None = None


def _resolve_db_path() -> Path:
    global _db_path
    if _db_path is None:
        settings = get_settings()
        # Prefer backend/data next to the app DB; override via RATE_LIMIT_DB_PATH.
        configured = getattr(settings, "rate_limit_db_path", "") or ""
        if configured:
            path = Path(configured)
        else:
            # settings._DATA_DIR is not exported; derive from database_url parent
            # or fall back to backend/data.
            backend_data = Path(__file__).resolve().parents[2] / "data"
            path = backend_data / "rate_limit.db"
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hits_key_ts ON hits (rate_key, ts)"
    )
    return conn


def _check_sqlite(ip: str, limit_per_hour: int) -> tuple[bool, int]:
    now = time.time()
    window = 3600.0
    cutoff = now - window
    with _db_lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM hits WHERE rate_key = ? AND ts <= ?", (ip, cutoff))
            row = conn.execute(
                "SELECT COUNT(*) FROM hits WHERE rate_key = ? AND ts > ?",
                (ip, cutoff),
            ).fetchone()
            count = int(row[0] if row else 0)
            if count >= limit_per_hour:
                return False, 0
            conn.execute("INSERT INTO hits (rate_key, ts) VALUES (?, ?)", (ip, now))
            return True, limit_per_hour - count - 1
        finally:
            conn.close()


def _check_memory(ip: str, limit_per_hour: int) -> tuple[bool, int]:
    now = time.time()
    window = 3600.0
    with _memory_lock:
        q = _memory_buckets.setdefault(ip, [])
        # Drop expired timestamps in place.
        keep = [ts for ts in q if now - ts <= window]
        if len(keep) >= limit_per_hour:
            _memory_buckets[ip] = keep
            return False, 0
        keep.append(now)
        _memory_buckets[ip] = keep
        return True, limit_per_hour - len(keep)


def check(ip: str, limit_per_hour: int) -> tuple[bool, int]:
    """Return (allowed, remaining)."""
    backend = (get_settings().rate_limit_backend or "sqlite").strip().lower()
    if backend == "memory":
        return _check_memory(ip, limit_per_hour)
    try:
        return _check_sqlite(ip, limit_per_hour)
    except Exception:  # noqa: BLE001 — fail open to in-process memory
        # Fail open to memory so a disk issue never hard-blocks chat.
        return _check_memory(ip, limit_per_hour)


def _retry_after_memory(rate_key: str) -> int:
    now = time.time()
    with _memory_lock:
        active = [ts for ts in _memory_buckets.get(rate_key, []) if now - ts <= 3600.0]
        if not active:
            return 1
        return max(1, int(ceil(active[0] + 3600.0 - now)))


def _retry_after_sqlite(rate_key: str) -> int:
    now = time.time()
    cutoff = now - 3600.0
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT MIN(ts) FROM hits WHERE rate_key = ? AND ts > ?",
                (rate_key, cutoff),
            ).fetchone()
        finally:
            conn.close()
    oldest = row[0] if row else None
    if not isinstance(oldest, (int, float)):
        return 1
    return max(1, int(ceil(float(oldest) + 3600.0 - now)))


def retry_after_seconds(rate_key: str) -> int:
    """Return the earliest safe retry delay for a currently limited key."""
    backend = (get_settings().rate_limit_backend or "sqlite").strip().lower()
    if backend == "memory":
        return _retry_after_memory(rate_key)
    try:
        return _retry_after_sqlite(rate_key)
    except Exception:  # noqa: BLE001 — the limiter itself must stay recoverable
        return _retry_after_memory(rate_key)


def reset_for_tests() -> None:
    """Clear counters (unit tests only)."""
    global _db_path
    with _memory_lock:
        _memory_buckets.clear()
    with _db_lock:
        path = _db_path
        _db_path = None
    if path and path.exists():
        path.unlink(missing_ok=True)
