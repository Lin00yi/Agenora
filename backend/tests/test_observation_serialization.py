from __future__ import annotations

from dataclasses import dataclass

from src.platform.observability.serialization import build_observation_tree


@dataclass
class _Observation:
    id: str
    parent_observation_id: str | None

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id}


def test_build_observation_tree_keeps_shared_span_topology() -> None:
    observations = [
        _Observation(id="root", parent_observation_id=None),
        _Observation(id="child", parent_observation_id="root"),
        _Observation(id="orphan", parent_observation_id="missing"),
    ]

    tree = build_observation_tree(observations)

    assert [node["id"] for node in tree] == ["root", "orphan"]
    assert [node["id"] for node in tree[0]["children"]] == ["child"]
    assert tree[1]["children"] == []
