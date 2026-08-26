"""Shared response shaping for persisted observability records."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def build_observation_tree(
    observations: Iterable[Any],
    *,
    serializer: Callable[[Any], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Nest Observation rows by parent id for every trace reader.

    Admin and conversation-scoped readers must render the same persisted span
    topology. Keeping this shaping at the observability boundary prevents their
    trees from drifting as runtime instrumentation evolves.
    """
    items = list(observations)
    to_dict = serializer or (lambda item: item.to_dict())
    by_id = {item.id: {**to_dict(item), "children": []} for item in items}
    roots: list[dict[str, Any]] = []
    for item in items:
        node = by_id[item.id]
        parent_id = item.parent_observation_id
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def user_trace_summary(trace: Any) -> dict[str, Any]:
    """Return a conversation owner's trace metadata without internal prompts."""
    payload = trace.to_summary_dict()
    payload["metadata"] = {}
    return payload


def user_observation(trace_observation: Any) -> dict[str, Any]:
    """Expose the observable path without leaking hidden model/RAG payloads.

    A conversation owner may inspect the input of an invoked tool, which matches
    the visible action in chat. Generation and generic-span inputs can contain
    the system prompt or retrieved material, so they stay server-only. Tool
    outputs can contain retrieved or third-party data and are likewise omitted.
    """
    payload = trace_observation.to_dict()
    metadata = payload.get("metadata")
    payload["metadata"] = (
        {"tool": metadata["tool"]}
        if isinstance(metadata, dict) and isinstance(metadata.get("tool"), str)
        else {}
    )
    payload["input_preview"] = (
        payload.get("input_preview") if payload.get("type") == "tool" else None
    )
    payload["output_preview"] = None
    return payload
