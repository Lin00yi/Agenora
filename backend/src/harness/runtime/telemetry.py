"""Safe, compact execution telemetry for persisted chat traces.

The browser and durable conversation metadata need enough information to
evaluate a ReAct turn, but must never retain raw tool arguments, tool results,
prompts, or provider payloads.  This module is deliberately state-only and
side-effect free so its redaction contract has straightforward unit coverage.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def _safe_scope(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "general")
    selected = value.get("selected_kb_ids")
    selected_ids = [str(item)[:80] for item in selected if str(item).strip()] if isinstance(selected, list) else []
    route = value.get("route")
    safe_route: dict[str, Any] = {}
    if isinstance(route, dict):
        for key in ("needs_retrieval", "source", "confidence", "reason", "candidate_count", "latency_ms"):
            raw = route.get(key)
            if isinstance(raw, bool | int | float):
                safe_route[key] = raw
            elif isinstance(raw, str):
                safe_route[key] = raw[:120]
    return {
        "kind": kind[:40],
        "selected_kb_ids": selected_ids[:3],
        **({"route": safe_route} if safe_route else {}),
    }


def summarize_runtime_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Return only aggregate, safe execution signals from one graph state."""
    source = state or {}
    names: Counter[str] = Counter()
    errors = 0
    for entry in source.get("tool_call_log") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            names[name.strip()[:80]] += 1
        if entry.get("error"):
            errors += 1

    iterations = source.get("iterations")
    return {
        "iterations": max(0, int(iterations or 0)),
        "tool_calls": dict(sorted(names.items())),
        "tool_call_total": sum(names.values()),
        "tool_error_total": errors,
        "web_search_calls": max(0, int(source.get("web_search_call_count") or 0)),
        "web_search_evidence": max(0, int(source.get("web_search_evidence_count") or 0)),
        **({"scope": scope} if (scope := _safe_scope(source.get("runtime_scope"))) else {}),
    }
