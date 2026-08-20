"""Closed task-DAG contract used by the Planner and Supervisor."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

TaskType = Literal["qa_chat", "qa_kb", "kb_route", "qa_orders"]
Capability = Literal["chat", "web_search", "kb_read", "kb_route", "orders_read", "refund_prepare", "refund_confirm"]
TaskStatus = Literal["pending", "done", "skipped"]

ALLOWED_TASK_TYPES = frozenset({"qa_chat", "qa_kb", "kb_route", "qa_orders"})
ALLOWED_CAPABILITIES = frozenset({"chat", "web_search", "kb_read", "kb_route", "orders_read", "refund_prepare", "refund_confirm"})
# A small upper bound keeps a single conversational turn auditable while still
# allowing a fan-out of independent read tasks followed by an aggregation task.
MAX_TASKS = 6

TYPE_DEFAULT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "qa_chat": ("chat", "web_search"),
    "qa_kb": ("kb_read",),
    "kb_route": ("kb_route",),
    "qa_orders": ("orders_read", "refund_prepare", "refund_confirm"),
}
TYPE_PREFERRED_AGENT: dict[str, str] = {
    "qa_chat": "chat",
    "qa_kb": "rag",
    "kb_route": "kb_router",
    "qa_orders": "orders",
}


class TaskNode(TypedDict, total=False):
    id: str
    type: str
    capabilities: list[str]
    depends_on: list[str]
    agent: str
    on_fail: str
    instruction: str
    resource_key: str
    requires_approval: bool


class TaskDag(TypedDict, total=False):
    tasks: list[TaskNode]
    reason: str
    source: str
    confidence: str
    latency_ms: int


def dag_single(*, task_type: str, reason: str, source: str, confidence: str = "high", latency_ms: int = 0) -> TaskDag:
    return {
        "tasks": [{"id": "task_1", "type": task_type, "capabilities": list(TYPE_DEFAULT_CAPABILITIES.get(task_type) or ()), "depends_on": [], "on_fail": "abort"}],
        "reason": reason,
        "source": source,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }


def dag_kb_then_chat(*, reason: str, source: str, confidence: str = "medium", latency_ms: int = 0) -> TaskDag:
    return {
        "tasks": [
            {"id": "task_1", "type": "qa_kb", "capabilities": ["kb_read"], "depends_on": [], "on_fail": "abort"},
            {"id": "task_2", "type": "qa_chat", "capabilities": ["chat", "web_search"], "depends_on": ["task_1"], "on_fail": "skip"},
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
    tasks = [dict(task) for task in (dag.get("tasks") or [])]
    existing_ids = {str(task.get("id")) for task in tasks}
    if any(task.get("type") == "qa_chat" or task.get("agent") == "chat" for task in tasks):
        return dag
    follow_id = "task_follow_chat"
    index = 2
    while follow_id in existing_ids:
        follow_id = f"task_{index}"
        index += 1
    parents = [str(task.get("id")) for task in tasks if task.get("id")]
    tasks.append({"id": follow_id, "type": "qa_chat", "capabilities": ["chat", "web_search"], "depends_on": parents[-1:] if parents else [], "on_fail": "skip"})
    return {**dag, "tasks": tasks, "reason": reason}  # type: ignore[typeddict-item]


def topology_key(tasks: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(task.get("type") or "") for task in tasks)
