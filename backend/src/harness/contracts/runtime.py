"""Request-scoped identity and dependency-neutral runtime context."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import EventEmitter


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Stable identifiers shared by HTTP, workers, traces, and sub-agents."""

    run_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None


@dataclass(slots=True)
class RunContext:
    """Minimal per-run harness context.

    Concrete provider clients, database sessions, and framework requests are
    deliberately absent. They are supplied by application services/adapters.
    """

    identity: RunIdentity = field(default_factory=RunIdentity)
    emit: EventEmitter | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    async def publish(self, event: dict[str, Any]) -> None:
        if self.emit is not None:
            await self.emit(event)  # type: ignore[arg-type]
