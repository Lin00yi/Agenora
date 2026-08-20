"""Settings connection-health use cases and circuit breaker.

Only transient provider failures count towards opening the circuit.  A bad
model ID or rejected credential remains visible to the caller instead of being
misclassified as a temporary outage.  The state is intentionally persisted on
``llm_connections`` so concurrent conversations share the same protection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.storage.database import get_session_factory
from src.capabilities.settings.domain.models import LLMConnection

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60


class LLMConnectionCircuitOpen(RuntimeError):
    """Raised before a provider call when its connection is temporarily open."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify_transient_llm_failure(exc: BaseException) -> str | None:
    """Return a safe category for retryable failures, or None for permanent ones."""
    text = str(exc).lower()
    if any(marker in text for marker in ("429", "rate limit", "too many requests")):
        return "rate_limited"
    if any(marker in text for marker in ("timeout", "timed out", "read timeout", "connect timeout")):
        return "timeout"
    if any(marker in text for marker in ("500", "502", "503", "504", "service unavailable", "bad gateway")):
        return "provider_5xx"
    if any(marker in text for marker in ("connection reset", "connection refused", "network error", "dns")):
        return "network"
    return None


async def assert_llm_connection_available(connection_id: str | None) -> None:
    """Allow a closed/expired circuit, reject only a still-open circuit."""
    if not connection_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        connection = await session.get(LLMConnection, connection_id)
        if connection is None or not connection.enabled:
            raise LLMConnectionCircuitOpen("configured connection is unavailable")
        until = connection.circuit_open_until
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until is not None and until > _now():
            raise LLMConnectionCircuitOpen("configured connection circuit is open")


async def record_llm_connection_success(connection_id: str | None) -> None:
    if not connection_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        connection = await session.get(LLMConnection, connection_id)
        if connection is None:
            return
        connection.consecutive_failures = 0
        connection.circuit_open_until = None
        connection.last_success_at = _now()
        connection.last_error_category = None
        await session.commit()


async def record_llm_connection_failure(connection_id: str | None, exc: BaseException) -> str | None:
    """Persist a transient failure and open after the bounded threshold."""
    category = classify_transient_llm_failure(exc)
    if not connection_id or category is None:
        return category
    factory = get_session_factory()
    async with factory() as session:
        connection = await session.get(LLMConnection, connection_id)
        if connection is None:
            return category
        now = _now()
        connection.consecutive_failures += 1
        connection.last_failure_at = now
        connection.last_error_category = category
        if connection.consecutive_failures >= FAILURE_THRESHOLD:
            connection.circuit_open_until = now + timedelta(seconds=COOLDOWN_SECONDS)
        await session.commit()
    return category
