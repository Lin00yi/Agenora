"""Task DAG types and closed topology templates.

Planner emits tasks with required capabilities; the registry binds an agent.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

TaskType = Literal["qa_chat", "qa_kb"]
Capability = Literal["chat", "web_search", "kb_read"]
TaskStatus = Literal["pending", "done", "skipped"]

ALLOWED_TASK_TYPES = frozenset({"qa_chat", "qa_kb"})
ALLOWED_CAPABILITIES = frozenset({"chat", "web_search", "kb_read"})
MAX_TASKS = 2

TYPE_DEFAULT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "qa_chat": ("chat", "web_search"),
    "qa_kb": ("kb_read",),
}

TYPE_PREFERRED_AGENT: dict[str, str] = {
    "qa_chat": "chat",
    "qa_kb": "rag",
}


class TaskNode(TypedDict, total=False):
    id: str
    type: str
    capabilities: list[str]
    depends_on: list[str]
    agent: str  # bound after registry match
    on_fail: str  # skip | abort


class TaskDag(TypedDict, total=False):
    tasks: list[TaskNode]
    reason: str
    source: str
    confidence: str
    latency_ms: int


def dag_single(
    *,
    task_type: str,
    reason: str,
    source: str,
    confidence: str = "high",
    latency_ms: int = 0,
) -> TaskDag:
    caps = list(TYPE_DEFAULT_CAPABILITIES.get(task_type) or ())
    return {
        "tasks": [
            {
                "id": "task_1",
                "type": task_type,
                "capabilities": caps,
                "depends_on": [],
                "on_fail": "abort",
            }
        ],
        "reason": reason,
        "source": source,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }


def dag_kb_then_chat(
    *,
    reason: str,
    source: str,
    confidence: str = "medium",
    latency_ms: int = 0,
) -> TaskDag:
    return {
        "tasks": [
            {
                "id": "task_1",
                "type": "qa_kb",
                "capabilities": ["kb_read"],
                "depends_on": [],
                "on_fail": "abort",
            },
            {
                "id": "task_2",
                "type": "qa_chat",
                "capabilities": ["chat", "web_search"],
                "depends_on": ["task_1"],
                "on_fail": "skip",
            },
        ],
        "reason": reason,
        "source": source,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }


def primary_agent(dag: TaskDag) -> str:
    tasks = dag.get("tasks") or []
    if not tasks:
        raise ValueError("empty DAG")
    first = tasks[0]
    return str(first.get("agent") or TYPE_PREFERRED_AGENT.get(str(first.get("type") or ""), "chat"))


def append_chat_followup(dag: TaskDag, *, reason: str) -> TaskDag:
    """Add qa_chat after existing tasks when empty-RAG handoff is needed."""
    tasks = [dict(t) for t in (dag.get("tasks") or [])]
    existing_ids = {str(t.get("id")) for t in tasks}
    if any(t.get("type") == "qa_chat" or t.get("agent") == "chat" for t in tasks):
        return dag
    follow_id = "task_follow_chat"
    n = 2
    while follow_id in existing_ids:
        follow_id = f"task_{n}"
        n += 1
    parents = [str(t.get("id")) for t in tasks if t.get("id")]
    tasks.append(
        {
            "id": follow_id,
            "type": "qa_chat",
            "capabilities": ["chat", "web_search"],
            "depends_on": parents[-1:] if parents else [],
            "on_fail": "skip",
        }
    )
    return {
        **dag,
        "tasks": tasks,  # type: ignore[typeddict-item]
        "reason": reason,
    }


def topology_key(tasks: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(t.get("type") or "") for t in tasks)
