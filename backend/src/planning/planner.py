"""Three-layer supervisor router: rule → triage → complex.

Output is a validated task DAG (capabilities + depends_on). A single
``target`` is derived from the first bound agent for compatibility.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal, TypedDict, TYPE_CHECKING

from src.planning.dag import (
    TaskDag,
    dag_kb_then_chat,
    dag_single,
    primary_agent,
)
from src.planning.validate import DagValidationError, validate_and_bind
from src.runtime.agent_loop.constants import (
    _RULE_MULTI_INTENT_KEYWORDS,
    _RULE_SKIP_KEYWORDS,
)
from src.agents.registry import AgentRegistry
from src.models.gateway import CostTracker, get_client, pick_model, with_cache_control
from src.observability import ageneration, traced
from src.settings import get_settings

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

RouteTarget = Literal["chat", "rag"]
RouteSource = Literal["rule", "triage", "complex", "fallback"]
RouteConfidence = Literal["high", "medium", "low"]
RouteMode = Literal["rule_only", "rule_triage", "layered"]

_ROUTE_TARGETS = frozenset({"chat", "rag"})
_ROUTE_CONFIDENCE = frozenset({"high", "medium", "low"})
_ROUTE_MODES = frozenset({"rule_only", "rule_triage", "layered"})
_TASK_TYPES_FROM_TARGET = {"chat": "qa_chat", "rag": "qa_kb"}


class RouteDecision(TypedDict):
    tasks: list[dict[str, Any]]
    target: str
    reason: str
    source: RouteSource
    confidence: RouteConfidence
    latency_ms: int


def normalize_route_mode(raw: str | None) -> RouteMode:
    mode = (raw or "layered").strip().lower()
    if mode in _ROUTE_MODES:
        return mode  # type: ignore[return-value]
    return "layered"


def looks_complex_query(query: str) -> bool:
    """Heuristic: prefer the complex layer for long / multi-intent turns."""
    text = " ".join((query or "").split())
    if not text:
        return False
    if len(text) >= 180:
        return True
    q_marks = text.count("？") + text.count("?")
    if q_marks >= 2:
        return True
    intent_hits = sum(1 for keyword in _RULE_MULTI_INTENT_KEYWORDS if keyword in text)
    has_connector = any(connector in text for connector in ("和", "及", "与", "、", ",", "，", "以及", "同时"))
    if has_connector and intent_hits >= 2:
        return True
    if intent_hits >= 3:
        return True
    return False


def _decision_from_dag(dag: TaskDag, *, registry: AgentRegistry, has_kb: bool) -> RouteDecision:
    bound = validate_and_bind(dag, registry=registry, has_kb=has_kb)
    target = primary_agent(bound)
    confidence_raw = str(bound.get("confidence") or "medium")
    confidence: RouteConfidence = (
        confidence_raw if confidence_raw in _ROUTE_CONFIDENCE else "medium"  # type: ignore[assignment]
    )
    source_raw = str(bound.get("source") or "fallback")
    source: RouteSource = source_raw if source_raw in {"rule", "triage", "complex", "fallback"} else "fallback"  # type: ignore[assignment]
    return {
        "tasks": list(bound.get("tasks") or []),
        "target": target,
        "reason": str(bound.get("reason") or "planned"),
        "source": source,
        "confidence": confidence,
        "latency_ms": int(bound.get("latency_ms") or 0),
    }


def fallback_route(*, has_kb: bool, registry: AgentRegistry) -> RouteDecision:
    available = registry.available(has_kb=has_kb)
    if has_kb and "rag" in available:
        return _decision_from_dag(
            dag_single(task_type="qa_kb", reason="kb_bound_default", source="fallback", confidence="medium"),
            registry=registry,
            has_kb=has_kb,
        )
    if "chat" in available:
        return _decision_from_dag(
            dag_single(
                task_type="qa_chat",
                reason="unbound_default",
                source="fallback",
                confidence="high",
            ),
            registry=registry,
            has_kb=has_kb,
        )
    if available:
        agent = available[0]
        task_type = "qa_kb" if agent == "rag" else "qa_chat"
        return _decision_from_dag(
            dag_single(task_type=task_type, reason="first_available", source="fallback", confidence="low"),
            registry=registry,
            has_kb=has_kb,
        )
    raise RuntimeError("agent registry is empty")


def rule_route(
    *,
    has_kb: bool,
    registry: AgentRegistry,
    user_query: str = "",
) -> RouteDecision | None:
    """Return only high-confidence rule decisions; None means escalate."""
    available = registry.available(has_kb=has_kb)
    text = " ".join((user_query or "").split())

    if not has_kb:
        if "chat" in available:
            return _decision_from_dag(
                dag_single(
                    task_type="qa_chat",
                    reason="unbound_default",
                    source="rule",
                    confidence="high",
                ),
                registry=registry,
                has_kb=has_kb,
            )
        return None

    if "chat" not in available and "rag" not in available:
        return None

    if not text:
        if "rag" in available:
            return _decision_from_dag(
                dag_single(
                    task_type="qa_kb",
                    reason="empty_query_kb_bound",
                    source="rule",
                    confidence="high",
                ),
                registry=registry,
                has_kb=has_kb,
            )
        return None

    if "chat" in available:
        if any(keyword in text for keyword in _RULE_SKIP_KEYWORDS):
            return _decision_from_dag(
                dag_single(
                    task_type="qa_chat",
                    reason="kb_bound_non_kb_intent",
                    source="rule",
                    confidence="high",
                ),
                registry=registry,
                has_kb=has_kb,
            )
        if len(text) <= 8 and not any(
            mark in text for mark in ("?", "？", "吗", "么", "如何", "怎么")
        ):
            if text in {"你好", "您好", "在吗", "早上好", "晚安", "谢谢", "多谢"}:
                return _decision_from_dag(
                    dag_single(
                        task_type="qa_chat",
                        reason="kb_bound_chitchat",
                        source="rule",
                        confidence="high",
                    ),
                    registry=registry,
                    has_kb=has_kb,
                )

    return None


def choose_initial_agent(
    *,
    has_kb: bool,
    registry: AgentRegistry,
    user_query: str = "",
) -> tuple[str, str]:
    """Sync rule/fallback helper for tests and callers that cannot await."""
    decision = rule_route(has_kb=has_kb, registry=registry, user_query=user_query)
    if decision is None:
        decision = fallback_route(has_kb=has_kb, registry=registry)
    return decision["target"], decision["reason"]


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty router response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start_candidates = [idx for idx in (stripped.find("{"), stripped.find("[")) if idx >= 0]
    if not start_candidates:
        raise ValueError("no JSON object found")
    start = min(start_candidates)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if end <= start:
        raise ValueError("no JSON object found")
    return json.loads(stripped[start : end + 1])


def _coerce_route_decision(
    payload: Any,
    *,
    registry: AgentRegistry,
    has_kb: bool,
    source: RouteSource,
    latency_ms: int,
) -> RouteDecision:
    if not isinstance(payload, dict):
        raise ValueError("router payload must be an object")
    confidence_raw = str(payload.get("confidence") or "medium").strip().lower()
    confidence: RouteConfidence = (
        confidence_raw if confidence_raw in _ROUTE_CONFIDENCE else "medium"  # type: ignore[assignment]
    )
    reason = str(payload.get("reason") or f"{source}_route").strip() or f"{source}_route"

    raw_tasks = payload.get("tasks")
    if isinstance(raw_tasks, list) and raw_tasks:
        dag: TaskDag = {
            "tasks": raw_tasks,  # type: ignore[typeddict-item]
            "reason": reason[:80],
            "source": source,
            "confidence": confidence,
            "latency_ms": latency_ms,
        }
        try:
            return _decision_from_dag(dag, registry=registry, has_kb=has_kb)
        except DagValidationError as exc:
            raise ValueError(str(exc)) from exc

    target = str(payload.get("target") or "").strip().lower()
    if target not in _ROUTE_TARGETS:
        raise ValueError(f"invalid target: {target}")
    available = registry.available(has_kb=has_kb)
    if target not in available:
        raise ValueError(f"invalid target: {target}")
    task_type = _TASK_TYPES_FROM_TARGET[target]
    if target == "rag" and payload.get("follow_chat") is True:
        dag = dag_kb_then_chat(reason=reason[:80], source=source, confidence=confidence, latency_ms=latency_ms)
    else:
        dag = dag_single(
            task_type=task_type,
            reason=reason[:80],
            source=source,
            confidence=confidence,
            latency_ms=latency_ms,
        )
    return _decision_from_dag(dag, registry=registry, has_kb=has_kb)


def _router_system_prompt(*, has_kb: bool, available: list[str], layer: RouteSource) -> str:
    kb_line = (
        "当前会话已绑定私有知识库。"
        if has_kb
        else "当前未绑定知识库，只能安排 qa_chat。"
    )
    depth = (
        "你是快速意图分流器（triage）。只输出单个任务，拿不准时把 confidence 设为 low。"
        "需要「先知识库再联网/通用」时不要自己排两步，把 confidence 设为 low。"
        if layer == "triage"
        else (
            "你是复杂意图路由器。绑定 KB 时：纯知识库事实用 [qa_kb]；"
            "知识库可能不够、还要通用回答或联网时用 [qa_kb → qa_chat]。"
            "不要把每道 KB 题都排成两步。"
        )
    )
    hybrid = (
        "绑定 KB 时允许 tasks 为 [qa_kb] 或 [qa_kb → qa_chat]。不要输出并行任务。"
        if has_kb
        else "只能输出一个 qa_chat 任务。"
    )
    two_step_example = (
        '{"tasks":['
        '{"id":"task_1","type":"qa_kb","capabilities":["kb_read"],"depends_on":[]},'
        '{"id":"task_2","type":"qa_chat","capabilities":["chat","web_search"],'
        '"depends_on":["task_1"]}],"confidence":"high","reason":"needs_kb_then_web"}'
        if layer == "complex" and has_kb
        else '{"tasks":[{"id":"task_1","type":"qa_kb","capabilities":["kb_read"],"depends_on":[]}],'
        '"confidence":"high","reason":"needs_kb_fact"}'
    )
    return (
        f"{depth}\n"
        f"{kb_line}\n"
        f"{hybrid}\n"
        "只输出 JSON，不要解释。\n"
        f"任务格式：\n{two_step_example}\n"
        "type 只能是 qa_kb 或 qa_chat。\n"
        "capabilities 只能来自 kb_read / chat / web_search。\n"
        "qa_chat 默认 capabilities 为 [chat, web_search]；qa_kb 为 [kb_read]。\n"
        "reason 必须是短 snake_case：needs_kb_fact / chitchat / general_chat / "
        "web_needed / multi_intent / non_kb / needs_kb_then_web。\n"
        "不要写长句，不要写 query_about_xxx。不要发明 Agent 名。\n"
        f"可用 agent 仅供对照：{', '.join(available)}。\n"
        "confidence=low 表示应升级到更强模型或保守回退。\n"
    )


@traced("supervisor_route_llm")
async def llm_route(
    *,
    user_query: str,
    has_kb: bool,
    registry: AgentRegistry,
    llm_cfg: "UserLLMConfig | None",
    cost: CostTracker,
    source: RouteSource,
) -> RouteDecision:
    """Ask one model layer for a structured route / DAG decision."""
    start = time.perf_counter()
    available = registry.available(has_kb=has_kb)
    if not available:
        raise RuntimeError("agent registry is empty")
    if len(available) == 1:
        only = available[0]
        task_type = "qa_kb" if only == "rag" else "qa_chat"
        return _decision_from_dag(
            dag_single(
                task_type=task_type,
                reason="single_available",
                source=source,
                confidence="high",
                latency_ms=int((time.perf_counter() - start) * 1000),
            ),
            registry=registry,
            has_kb=has_kb,
        )

    client = get_client(llm_cfg)
    model = pick_model([{"role": "user", "content": user_query}], [], llm_cfg)
    system_prompt = _router_system_prompt(has_kb=has_kb, available=available, layer=source)
    settings = get_settings()
    if llm_cfg is not None:
        is_anthropic = llm_cfg.provider == "anthropic"
    else:
        is_anthropic = settings.llm_provider == "anthropic"

    async with ageneration(
        f"supervisor.route.{source}",
        model=model,
        input={"query": user_query, "has_kb": has_kb},
    ) as gen:
        if not is_anthropic:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                max_tokens=512,
            )
            cost.add(model, getattr(resp, "usage", None), cfg=llm_cfg)
            text = resp.choices[0].message.content or ""
            if gen is not None:
                gen.update(output=text, usage=getattr(resp, "usage", None))
        else:
            resp = await client.messages.create(
                model=model,
                max_tokens=512,
                system=with_cache_control([{"type": "text", "text": system_prompt}], llm_cfg),
                messages=[{"role": "user", "content": user_query}],
            )
            cost.add(model, resp.usage, cfg=llm_cfg)
            text = "\n".join(
                block.text for block in resp.content if getattr(block, "type", "") == "text"
            )
            if gen is not None:
                gen.update(output=text, usage=resp.usage)

    parsed = _extract_json_object(text)
    return _coerce_route_decision(
        parsed,
        registry=registry,
        has_kb=has_kb,
        source=source,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )


def _normalize_llm_decision(
    decision: RouteDecision,
    *,
    registry: AgentRegistry,
    has_kb: bool,
) -> RouteDecision:
    """Accept mocked legacy {target:...} or a full DAG decision."""
    if decision.get("tasks"):
        try:
            return _decision_from_dag(
                {
                    "tasks": decision["tasks"],  # type: ignore[typeddict-item]
                    "reason": decision.get("reason") or "planned",
                    "source": decision.get("source") or "fallback",
                    "confidence": decision.get("confidence") or "medium",
                    "latency_ms": int(decision.get("latency_ms") or 0),
                },
                registry=registry,
                has_kb=has_kb,
            )
        except DagValidationError:
            return fallback_route(has_kb=has_kb, registry=registry)
    target = str(decision.get("target") or "")
    if target in _ROUTE_TARGETS:
        try:
            return _coerce_route_decision(
                decision,
                registry=registry,
                has_kb=has_kb,
                source=decision.get("source") or "fallback",  # type: ignore[arg-type]
                latency_ms=int(decision.get("latency_ms") or 0),
            )
        except ValueError:
            return fallback_route(has_kb=has_kb, registry=registry)
    return fallback_route(has_kb=has_kb, registry=registry)


@traced("supervisor_resolve_route")
async def resolve_agent_route(
    *,
    has_kb: bool,
    registry: AgentRegistry,
    user_query: str,
    cost: CostTracker,
    triage_llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    default_llm_cfg: "UserLLMConfig | None" = None,
    mode: str | None = None,
) -> RouteDecision:
    """Cascade: rule → triage → complex → fallback. Always a validated DAG."""
    settings = get_settings()
    route_mode = normalize_route_mode(mode or getattr(settings, "agent_route_mode", "layered"))

    rule = rule_route(has_kb=has_kb, registry=registry, user_query=user_query)
    if rule is not None:
        return rule

    if route_mode == "rule_only":
        return fallback_route(has_kb=has_kb, registry=registry)

    complex_query = looks_complex_query(user_query)
    triage_cfg = triage_llm_cfg or default_llm_cfg
    complex_cfg = complex_llm_cfg or (
        default_llm_cfg if complex_llm_cfg is None and complex_query else None
    )

    async def _run(source: RouteSource, cfg: "UserLLMConfig | None") -> RouteDecision | None:
        if cfg is None:
            return None
        try:
            raw = await llm_route(
                user_query=user_query,
                has_kb=has_kb,
                registry=registry,
                llm_cfg=cfg,
                cost=cost,
                source=source,
            )
            return _normalize_llm_decision(raw, registry=registry, has_kb=has_kb)
        except Exception:  # noqa: BLE001
            return None

    if route_mode == "layered" and complex_query and complex_cfg is not None:
        planned = await _run("complex", complex_cfg)
        return planned or fallback_route(has_kb=has_kb, registry=registry)

    if route_mode in {"rule_triage", "layered"} and triage_cfg is not None:
        triage = await _run("triage", triage_cfg)
        if triage is not None and triage["confidence"] in {"high", "medium"}:
            return triage
        if route_mode == "layered":
            planned = await _run("complex", complex_llm_cfg or default_llm_cfg)
            if planned is not None:
                return planned
        if triage is not None:
            return triage

    if route_mode == "layered":
        planned = await _run("complex", complex_llm_cfg or default_llm_cfg)
        if planned is not None:
            return planned

    return fallback_route(has_kb=has_kb, registry=registry)
