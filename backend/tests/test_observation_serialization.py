from __future__ import annotations

from dataclasses import dataclass

from src.platform.observability.serialization import build_observation_tree


@dataclass
class _Observation:
    id: str
    parent_observation_id: str | None

    type: str = "span"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "input_preview": "internal prompt",
            "output_preview": "retrieved result",
            "metadata": {"tool": "web_search", "private": "do not expose"},
        }


@dataclass
class _Trace:
    def to_summary_dict(self) -> dict[str, object]:
        return {"id": "trace", "metadata": {"prompt_trace": {"internal": True}}}


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


def test_user_observation_keeps_only_tool_input_and_safe_metadata() -> None:
    from src.platform.observability.serialization import user_observation, user_trace_summary

    generation = user_observation(_Observation(id="generation", parent_observation_id=None))
    tool = user_observation(_Observation(id="tool", parent_observation_id=None, type="tool"))

    assert generation["input_preview"] is None
    assert tool["input_preview"] == "internal prompt"
    assert generation["output_preview"] is None
    assert tool["output_preview"] is None
    assert tool["metadata"] == {"tool": "web_search"}
    assert user_trace_summary(_Trace())["metadata"] == {}
