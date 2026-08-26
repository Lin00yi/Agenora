"""Shared response shaping for persisted observability records."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_observation_tree(observations: Iterable[Any]) -> list[dict[str, Any]]:
    """Nest Observation rows by parent id for every trace reader.

    Admin and conversation-scoped readers must render the same persisted span
    topology. Keeping this shaping at the observability boundary prevents their
    trees from drifting as runtime instrumentation evolves.
    """
    items = list(observations)
    by_id = {item.id: {**item.to_dict(), "children": []} for item in items}
    roots: list[dict[str, Any]] = []
    for item in items:
        node = by_id[item.id]
        parent_id = item.parent_observation_id
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots
