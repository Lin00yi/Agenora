"""Task DAG validation and capability matching."""
from __future__ import annotations

import pytest

from src.agent.main_agent.dag import dag_kb_then_chat, dag_single
from src.agent.main_agent.validate import DagValidationError, match_agent, validate_and_bind
from src.agent.registry import build_default_agent_registry


def test_validate_single_chat() -> None:
    reg = build_default_agent_registry()
    bound = validate_and_bind(
        dag_single(task_type="qa_chat", reason="unbound_default", source="rule"),
        registry=reg,
        has_kb=False,
    )
    assert bound["tasks"][0]["agent"] == "chat"
    assert bound["tasks"][0]["capabilities"] == ["chat", "web_search"]


def test_validate_kb_then_chat() -> None:
    reg = build_default_agent_registry()
    bound = validate_and_bind(
        dag_kb_then_chat(reason="needs_kb_then_web", source="complex"),
        registry=reg,
        has_kb=True,
    )
    assert [t["agent"] for t in bound["tasks"]] == ["rag", "chat"]
    assert bound["tasks"][1]["depends_on"] == ["task_1"]


def test_qa_kb_without_kb_fails() -> None:
    reg = build_default_agent_registry()
    with pytest.raises(DagValidationError, match="requires a bound knowledge base"):
        validate_and_bind(
            dag_single(task_type="qa_kb", reason="x", source="rule"),
            registry=reg,
            has_kb=False,
        )


def test_unknown_capability_fails() -> None:
    reg = build_default_agent_registry()
    with pytest.raises(DagValidationError, match="unknown capability"):
        validate_and_bind(
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "type": "qa_chat",
                        "capabilities": ["refund"],
                        "depends_on": [],
                    }
                ]
            },
            registry=reg,
            has_kb=False,
        )


def test_cycle_fails() -> None:
    reg = build_default_agent_registry()
    with pytest.raises(DagValidationError, match="earlier task"):
        validate_and_bind(
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "type": "qa_kb",
                        "capabilities": ["kb_read"],
                        "depends_on": ["task_2"],
                    },
                    {
                        "id": "task_2",
                        "type": "qa_chat",
                        "capabilities": ["chat"],
                        "depends_on": ["task_1"],
                    },
                ]
            },
            registry=reg,
            has_kb=True,
        )


def test_parallel_topology_rejected() -> None:
    reg = build_default_agent_registry()
    with pytest.raises(DagValidationError, match="topology not allowed"):
        validate_and_bind(
            {
                "tasks": [
                    {
                        "id": "a",
                        "type": "qa_chat",
                        "capabilities": ["chat"],
                        "depends_on": [],
                    },
                    {
                        "id": "b",
                        "type": "qa_kb",
                        "capabilities": ["kb_read"],
                        "depends_on": [],
                    },
                ]
            },
            registry=reg,
            has_kb=True,
        )


def test_match_agent_prefers_canonical() -> None:
    reg = build_default_agent_registry()
    assert (
        match_agent(reg, task_type="qa_kb", capabilities=["kb_read"], has_kb=True)
        == "rag"
    )
    assert (
        match_agent(reg, task_type="qa_chat", capabilities=["chat", "web_search"], has_kb=True)
        == "chat"
    )
