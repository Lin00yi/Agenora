"""Safe, transport-neutral events emitted during an AI run."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

RunEventKind = Literal[
    "dag_ready",
    "agent_route",
    "agent_handoff",
    "kb_routed",
    "report_start",
    "token",
    "context_ready",
    "done",
    "error",
]


class RunEvent(TypedDict, total=False):
    """Whitelisted event envelope used by SSE and observability adapters.

    Event-specific fields intentionally remain optional: the harness carries a
    single event stream while the transport decides how to serialize it.
    Raw prompts, credentials, and provider payloads do not belong here.
    """

    event: RunEventKind | str
    agent: str
    task_id: str
    reason: str
    source: str
    confidence: str
    text: str
    kb_id: str
    name: str
    tasks: list[dict[str, Any]]
    metadata: dict[str, Any]


EventEmitter = Callable[[RunEvent], Awaitable[None]]
