"""Validate a task DAG and bind each task to a registered agent."""
from __future__ import annotations

from typing import Any

from src.planning.dag import (
    ALLOWED_CAPABILITIES,
    ALLOWED_TASK_TYPES,
    MAX_TASKS,
    TYPE_DEFAULT_CAPABILITIES,
    TYPE_PREFERRED_AGENT,
    TaskDag,
    TaskNode,
    topology_key,
)
from src.agents.registry import AgentRegistry


class DagValidationError(ValueError):
    pass


# v1 whitelist: single qa_* or qa_kb → qa_chat.
_ALLOWED_TOPOLOGIES = {
    ("qa_chat",),
    ("qa_kb",),
    ("qa_kb", "qa_chat"),
}


def match_agent(
    registry: AgentRegistry,
    *,
    task_type: str,
    capabilities: list[str],
    has_kb: bool,
) -> str:
    needed = set(capabilities)
    available = registry.available(has_kb=has_kb)
    scored: list[tuple[int, str]] = []
    preferred = TYPE_PREFERRED_AGENT.get(task_type)
    for agent_id in available:
        spec = registry.get(agent_id)
        provided = set(spec.provides)
        if needed and not needed <= provided:
            continue
        extra = len(provided - needed)
        # Prefer the type's canonical agent, then the tightest capability set.
        bonus = 0 if agent_id == preferred else 10
        scored.append((bonus + extra, agent_id))
    if not scored and preferred in available and not needed:
        return preferred
    if not scored:
        raise DagValidationError(
            f"no agent provides {sorted(needed)} for type={task_type} has_kb={has_kb}"
        )
    scored.sort()
    return scored[0][1]


def _normalize_task(raw: Any, *, index: int) -> TaskNode:
    if not isinstance(raw, dict):
        raise DagValidationError("task must be an object")
    task_id = str(raw.get("id") or f"task_{index + 1}").strip()
    if not task_id:
        raise DagValidationError("task id must be non-empty")
    task_type = str(raw.get("type") or "").strip().lower()
    if task_type not in ALLOWED_TASK_TYPES:
        raise DagValidationError(f"unknown task type: {task_type}")
    caps_raw = raw.get("capabilities")
    if caps_raw is None:
        caps = list(TYPE_DEFAULT_CAPABILITIES[task_type])
    elif isinstance(caps_raw, list):
        caps = []
        for item in caps_raw:
            cap = str(item).strip().lower()
            if cap not in ALLOWED_CAPABILITIES:
                raise DagValidationError(f"unknown capability: {cap}")
            if cap not in caps:
                caps.append(cap)
        if not caps:
            caps = list(TYPE_DEFAULT_CAPABILITIES[task_type])
    else:
        raise DagValidationError("capabilities must be a list")
    depends_raw = raw.get("depends_on") or []
    if not isinstance(depends_raw, list):
        raise DagValidationError("depends_on must be a list")
    depends_on = [str(x).strip() for x in depends_raw if str(x).strip()]
    on_fail = str(raw.get("on_fail") or "abort").strip().lower()
    if on_fail not in {"skip", "abort"}:
        on_fail = "abort"
    node: TaskNode = {
        "id": task_id,
        "type": task_type,
        "capabilities": caps,
        "depends_on": depends_on,
        "on_fail": on_fail,
    }
    return node


def validate_and_bind(
    payload: Any,
    *,
    registry: AgentRegistry,
    has_kb: bool,
) -> TaskDag:
    """Normalize, whitelist topology, bind agents. Raises DagValidationError."""
    if not isinstance(payload, dict):
        raise DagValidationError("DAG payload must be an object")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise DagValidationError("tasks must be a non-empty list")
    if len(raw_tasks) > MAX_TASKS:
        raise DagValidationError(f"too many tasks: {len(raw_tasks)}")

    tasks = [_normalize_task(item, index=i) for i, item in enumerate(raw_tasks)]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise DagValidationError("duplicate task id")
    id_set = set(ids)
    for task in tasks:
        for dep in task.get("depends_on") or []:
            if dep not in id_set:
                raise DagValidationError(f"unknown depends_on: {dep}")
            if dep == task["id"]:
                raise DagValidationError("task cannot depend on itself")

    # Acyclic: ids must only depend on earlier tasks (stable order after normalize).
    seen: set[str] = set()
    for task in tasks:
        for dep in task.get("depends_on") or []:
            if dep not in seen:
                raise DagValidationError("depends_on must refer to an earlier task")
        seen.add(task["id"])

    topo = topology_key(list(tasks))
    if topo not in _ALLOWED_TOPOLOGIES:
        raise DagValidationError(f"topology not allowed: {topo}")

    if topo[0] == "qa_kb" and not has_kb:
        raise DagValidationError("qa_kb requires a bound knowledge base")

    bound: list[TaskNode] = []
    for task in tasks:
        agent = match_agent(
            registry,
            task_type=str(task["type"]),
            capabilities=list(task.get("capabilities") or []),
            has_kb=has_kb,
        )
        bound.append({**task, "agent": agent})

    reason = str(payload.get("reason") or "planned").strip() or "planned"
    source = str(payload.get("source") or "fallback")
    confidence = str(payload.get("confidence") or "medium")
    try:
        latency_ms = int(payload.get("latency_ms") or 0)
    except (TypeError, ValueError):
        latency_ms = 0
    return {
        "tasks": bound,
        "reason": reason[:80],
        "source": source,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }


def ready_tasks(dag: TaskDag, status: dict[str, str]) -> list[TaskNode]:
    """Return pending tasks whose dependencies are all done."""
    ready: list[TaskNode] = []
    for task in dag.get("tasks") or []:
        task_id = str(task.get("id") or "")
        if status.get(task_id, "pending") != "pending":
            continue
        deps = list(task.get("depends_on") or [])
        if all(status.get(dep) == "done" for dep in deps):
            ready.append(task)
    return ready
