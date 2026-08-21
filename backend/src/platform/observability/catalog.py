"""Stable lifecycle metadata for persisted Trace observation names.

Trace rows are audit records: an observation name must remain interpretable
after the implementation that emitted it has been retired.  This registry is
therefore deliberately separate from the executable graph/tool registry.
"""
from __future__ import annotations

from typing import Literal


TraceNodeLifecycle = Literal["active", "legacy", "retired", "unknown"]

# Increment only when the persisted trace contract changes in an incompatible
# way.  It lets the UI distinguish a historical tree from a current runtime
# without rewriting audit records.
TRACE_SCHEMA_VERSION = 2

_RETIRED_NAMES = frozenset(
    {
        "amap_search",
        "generate_travel_report",
        "get_weather",
        "search_restaurant_kb",
    }
)

_ACTIVE_NAMES = frozenset(
    {
        "auto_kb_route",
        "auto_kb_route.llm",
        "build_context",
        "call_tools",
        "confirm_refund",
        "generate_kb_report",
        "get_current_time",
        "get_order",
        "kb_search",
        "list_orders",
        "llm.chat_with_tools",
        "prepare_refund",
        "query_policy",
        "reason",
        "scope",
        "search_kg",
        "search_kb",
        "web_search",
    }
)


def observation_lifecycle(name: str) -> TraceNodeLifecycle:
    """Classify a persisted node without mutating its historical name."""
    if name in _RETIRED_NAMES:
        return "retired"
    if name.startswith("supervisor_") or name.startswith("supervisor."):
        return "legacy"
    if name in _ACTIVE_NAMES:
        return "active"
    return "unknown"
