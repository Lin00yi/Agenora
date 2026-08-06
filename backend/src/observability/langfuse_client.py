"""Lazy Langfuse client bootstrap (no-op without keys / package)."""
from __future__ import annotations

from typing import Any

import structlog

from src.settings import get_settings

log = structlog.get_logger()

_client: Any | None = None
_init_attempted = False
_warned_missing_keys = False
_warned_import = False


def langfuse_configured() -> bool:
    """True when Langfuse export should be attempted."""
    s = get_settings()
    if not s.langfuse_enabled:
        return False
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return False
    return True


def get_langfuse() -> Any | None:
    """Return a Langfuse client, or None when disabled / unavailable."""
    global _client, _init_attempted, _warned_missing_keys, _warned_import

    s = get_settings()
    if not s.langfuse_enabled:
        return None

    if not (s.langfuse_public_key and s.langfuse_secret_key):
        if not _warned_missing_keys:
            log.warning(
                "langfuse_disabled_missing_keys",
                hint="Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY, or LANGFUSE_ENABLED=false",
            )
            _warned_missing_keys = True
        return None

    if _client is not None:
        return _client
    if _init_attempted:
        return None
    _init_attempted = True

    try:
        from langfuse import Langfuse
    except ImportError:
        if not _warned_import:
            log.warning(
                "langfuse_not_installed",
                hint="pip install langfuse (or reinstall backend deps)",
            )
            _warned_import = True
        return None

    try:
        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host or "https://cloud.langfuse.com",
            sample_rate=float(s.langfuse_sample_rate),
        )
        log.info("langfuse_enabled", host=s.langfuse_host)
        return _client
    except Exception as exc:  # noqa: BLE001
        log.warning("langfuse_init_failed", error=str(exc))
        return None


def reset_langfuse_for_tests() -> None:
    """Clear cached client (unit tests only)."""
    global _client, _init_attempted, _warned_missing_keys, _warned_import
    _client = None
    _init_attempted = False
    _warned_missing_keys = False
    _warned_import = False
