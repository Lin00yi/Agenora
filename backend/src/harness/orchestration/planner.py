"""Harness-owned three-layer supervisor planner: rule → triage → complex.

Output is a validated task DAG (capabilities + depends_on). A single
``target`` is derived from the first bound agent for compatibility.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal, TypedDict, TYPE_CHECKING

from src.harness.orchestration.dag import (
    TaskDag,
    dag_kb_then_chat,
    dag_single,
    primary_agent,
)
from src.harness.orchestration.validation import DagValidationError, validate_and_bind
from src.harness.runtime.agent_loop.constants import (
    _RULE_MULTI_INTENT_KEYWORDS,
    _RULE_SKIP_KEYWORDS,
)
from src.harness.orchestration.registry import AgentRegistry
from src.harness.orchestration.intent import (
    IntentAssessment,
    IntentSource,
    fallback_assessment,
    rule_classify,
    understand_query,
)
from src.platform.llm import CostTracker, get_client, pick_model, with_cache_control
from src.platform.observability import ageneration, traced
from src.settings import get_settings

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig

RouteTarget = Literal["chat", "rag", "kb_router", "orders"]
RouteSource = Literal["rule", "triage", "complex", "fallback"]
RouteConfidence = Literal["high", "medium", "low"]
RouteMode = Literal["rule_only", "rule_triage", "layered"]

_ROUTE_TARGETS = frozenset({"chat", "rag", "kb_router", "orders"})
_ROUTE_CONFIDENCE = frozenset({"high", "medium", "low"})
_ROUTE_MODES = frozenset({"rule_only", "rule_triage", "layered"})
_TASK_TYPES_FROM_TARGET = {"chat": "qa_chat", "rag": "qa_kb", "kb_router": "kb_route", "orders": "qa_orders"}

class RouteDecision(TypedDict):
    tasks: list[dict[str, Any]]
    target: str
    reason: str
    source: RouteSource
    confidence: RouteConfidence
    latency_ms: int
    intent: dict[str, Any]


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


def _decision_from_dag(
    dag: TaskDag,
    *,
    registry: AgentRegistry,
    has_kb: bool,
    intent: IntentAssessment | None = None,
) -> RouteDecision:
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
        "intent": intent.trace_metadata() if intent is not None else {},
    }


def _plan_from_intent(
    assessment: IntentAssessment,
    *,
    has_kb: bool,
    has_routable_kbs: bool,
    registry: AgentRegistry,
) -> RouteDecision:
    """Compile a classified intent into a closed, capability-checked DAG."""
    available = registry.available(has_kb=has_kb)
    if assessment.domain == "orders" and "orders" in available:
        task_type = "qa_orders"
    elif assessment.domain == "knowledge" and has_kb and "rag" in available:
        task_type = "qa_kb"
    elif assessment.domain == "knowledge" and has_routable_kbs and "kb_router" in available:
        task_type = "kb_route"
    else:
        task_type = "qa_chat"
    return _decision_from_dag(
        dag_single(
            task_type=task_type,
            reason=assessment.rationale or assessment.intent,
            source=assessment.source,
            confidence=assessment.confidence,
            latency_ms=assessment.latency_ms,
        ),
        registry=registry,
        has_kb=has_kb,
        intent=assessment,
    )


def fallback_route(*, has_kb: bool, registry: AgentRegistry) -> RouteDecision:
    available = [
        agent for agent in registry.available(has_kb=has_kb) if agent != "kb_router"
    ]
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
        task_type = "qa_kb" if agent == "rag" else "qa_orders" if agent == "orders" else "qa_chat"
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
    has_routable_kbs: bool = False,
) -> RouteDecision | None:
    """Return only high-confidence rule decisions; None means escalate."""
    available = registry.available(has_kb=has_kb)
    if has_kb:
        available = [agent for agent in available if agent != "kb_router"]
    text = " ".join((user_query or "").split())

    assessment = rule_classify(understand_query(text))
    if assessment is not None:
        return _plan_from_intent(
            assessment,
            has_kb=has_kb,
            has_routable_kbs=has_routable_kbs,
            registry=registry,
        )

    if not has_kb:
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
    has_routable_kbs: bool = False,
) -> tuple[str, str]:
    """Sync rule/fallback helper for tests and callers that cannot await."""
    decision = rule_route(
        has_kb=has_kb,
        has_routable_kbs=has_routable_kbs,
        registry=registry,
        user_query=user_query,
    )
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
    if target == "kb_router" and has_kb:
        raise ValueError("kb_router is only valid for an unbound conversation")
    available = registry.available(has_kb=has_kb)
    if has_kb:
        available = [agent for agent in available if agent != "kb_router"]
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
    orders_line = "订单查询、退款申请和确认退款必须使用 qa_orders。" if "orders" in available else ""
    kb_line = (
        "当前会话已绑定私有知识库。"
        if has_kb
        else "当前未绑定知识库；普通问题用 qa_chat，订单操作可用 qa_orders。"
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
        else "只输出一个任务：普通问题为 qa_chat，订单操作为 qa_orders。"
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
        f"{kb_line}\n{orders_line}\n"
        f"{hybrid}\n"
        "只输出 JSON，不要解释。\n"
        f"任务格式：\n{two_step_example}\n"
        "type 只能是 qa_kb、qa_chat 或 qa_orders。\n"
        "capabilities 只能来自 kb_read / chat / web_search / orders_read / refund_prepare / refund_confirm。\n"
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
    if has_kb:
        available = [agent for agent in available if agent != "kb_router"]
    if not available:
        raise RuntimeError("agent registry is empty")
    if len(available) == 1:
        only = available[0]
        task_type = "qa_kb" if only == "rag" else "qa_orders" if only == "orders" else "qa_chat"
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


def _coerce_intent_assessment(
    payload: Any,
    *,
    source: IntentSource,
    latency_ms: int,
) -> IntentAssessment:
    if not isinstance(payload, dict):
        raise ValueError("intent payload must be an object")
    domain = str(payload.get("domain") or "general").strip().lower()
    intent = str(payload.get("intent") or "general_chat").strip().lower()
    risk = str(payload.get("risk") or "none").strip().lower()
    confidence = str(payload.get("confidence") or "low").strip().lower()
    valid_domains = {"general", "knowledge", "orders"}
    valid_intents = {
        "general_chat", "knowledge_lookup", "order_lookup", "refund_prepare",
        "refund_confirm", "refund_information",
    }
    valid_risks = {"none", "read", "write", "confirmation_required"}
    if domain not in valid_domains or intent not in valid_intents or risk not in valid_risks:
        raise ValueError("invalid intent classification")
    if confidence not in _ROUTE_CONFIDENCE:
        confidence = "low"
    slots = payload.get("missing_slots") or []
    if not isinstance(slots, list):
        slots = []
    allowed_slots = {"order_id", "refund_reason", "approval_id"}
    missing = tuple(
        value for value in (str(item).strip() for item in slots)
        if value in allowed_slots
    )
    return IntentAssessment(
        domain=domain,  # type: ignore[arg-type]
        intent=intent,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        missing_slots=missing,
        confidence=confidence,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        rationale=str(payload.get("rationale") or intent)[:80],
    )


def _intent_system_prompt(*, layer: RouteSource, has_kb: bool, has_routable_kbs: bool) -> str:
    return f"""你是{'轻量' if layer == 'triage' else '高精度'}意图识别器，不是任务规划器。
保留用户原意，不改写订单号、金额、确认文本或身份信息。只输出 JSON：
{{"domain":"general|knowledge|orders","intent":"general_chat|knowledge_lookup|order_lookup|refund_prepare|refund_confirm|refund_information","risk":"none|read|write|confirmation_required","missing_slots":["order_id|refund_reason|approval_id"],"confidence":"high|medium|low","rationale":"short_snake_case"}}
规则：订单查询为 orders/order_lookup/read；退款申请为 orders/refund_prepare/write；只有精确确认退款才是 refund_confirm/confirmation_required；退款政策、规则、条件为 refund_information/read。
当前是否已绑定知识库：{has_kb}；是否有可路由知识库：{has_routable_kbs}。拿不准返回 low，不能输出 tasks、agent、工具调用或解释。"""


@traced("supervisor_classify_intent")
async def llm_classify_intent(
    *,
    user_query: str,
    has_kb: bool,
    has_routable_kbs: bool,
    llm_cfg: "UserLLMConfig | None",
    cost: CostTracker,
    source: IntentSource,
) -> IntentAssessment:
    start = time.perf_counter()
    client = get_client(llm_cfg)
    model = pick_model([{"role": "user", "content": user_query}], [], llm_cfg)
    settings = get_settings()
    is_anthropic = llm_cfg.provider == "anthropic" if llm_cfg is not None else settings.llm_provider == "anthropic"
    system_prompt = _intent_system_prompt(
        layer=source,
        has_kb=has_kb,
        has_routable_kbs=has_routable_kbs,
    )
    async with ageneration(
        f"supervisor.intent.{source}", model=model, input={"query": user_query, "has_kb": has_kb}
    ) as gen:
        if is_anthropic:
            response = await client.messages.create(
                model=model,
                max_tokens=256,
                system=with_cache_control([{"type": "text", "text": system_prompt}], llm_cfg),
                messages=[{"role": "user", "content": user_query}],
            )
            cost.add(model, response.usage, cfg=llm_cfg)
            text = "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            usage = response.usage
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}],
                max_tokens=256,
            )
            usage = getattr(response, "usage", None)
            cost.add(model, usage, cfg=llm_cfg)
            text = response.choices[0].message.content or ""
        if gen is not None:
            gen.update(output=text, usage=usage)
    return _coerce_intent_assessment(
        _extract_json_object(text), source=source, latency_ms=int((time.perf_counter() - start) * 1000)
    )


def _needs_multi_agent_plan(query: str, assessment: IntentAssessment) -> bool:
    """Avoid an extra planner call for atomic and all write operations."""
    if assessment.risk in {"write", "confirmation_required"}:
        return False
    text = " ".join((query or "").split())
    return any(token in text for token in ("同时", "并且", "以及", "和", "、", "对比", "比较", "汇总"))


def _dag_planner_prompt(
    *,
    assessment: IntentAssessment,
    has_kb: bool,
    available: list[str],
) -> str:
    return f"""你是受限 DAG 规划器。根据已完成的意图识别生成 JSON，不执行工具：
intent={assessment.trace_metadata()}
has_kb={has_kb}; available_agents={available}
只输出 {{"tasks":[...],"reason":"short_snake_case","confidence":"high|medium|low"}}。
Task 仅可用：qa_chat([chat,web_search])、qa_kb([kb_read]，仅 has_kb=true)、qa_orders([orders_read,refund_prepare,refund_confirm])。
每项含 id,type,capabilities,depends_on,on_fail，可选 instruction。最多 6 项，依赖只能指向前项。
独立只读任务可并行；需要整合时最后的 qa_chat 依赖所有前置任务。不要生成 kb_route 与其他任务混用。
安全：risk=write 或 confirmation_required 时只能生成一个 qa_orders，不能把退款确认和准备放在同一 DAG；本请求若不满足条件就只生成一个最小只读任务。"""


@traced("supervisor_plan_dag")
async def llm_generate_dag(
    *,
    user_query: str,
    assessment: IntentAssessment,
    has_kb: bool,
    registry: AgentRegistry,
    llm_cfg: "UserLLMConfig | None",
    cost: CostTracker,
) -> RouteDecision:
    """Generate then validate a DAG only after intent/risk classification."""
    start = time.perf_counter()
    client = get_client(llm_cfg)
    model = pick_model([{"role": "user", "content": user_query}], [], llm_cfg)
    settings = get_settings()
    is_anthropic = llm_cfg.provider == "anthropic" if llm_cfg is not None else settings.llm_provider == "anthropic"
    prompt = _dag_planner_prompt(
        assessment=assessment,
        has_kb=has_kb,
        available=registry.available(has_kb=has_kb),
    )
    async with ageneration(
        "supervisor.plan_dag", model=model, input={"query": user_query, "intent": assessment.trace_metadata()}
    ) as gen:
        if is_anthropic:
            response = await client.messages.create(
                model=model,
                max_tokens=512,
                system=with_cache_control([{"type": "text", "text": prompt}], llm_cfg),
                messages=[{"role": "user", "content": user_query}],
            )
            usage = response.usage
            cost.add(model, usage, cfg=llm_cfg)
            text = "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_query}],
                max_tokens=512,
            )
            usage = getattr(response, "usage", None)
            cost.add(model, usage, cfg=llm_cfg)
            text = response.choices[0].message.content or ""
        if gen is not None:
            gen.update(output=text, usage=usage)
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("DAG planner payload must be an object")
    return _decision_from_dag(
        {
            "tasks": payload.get("tasks") or [],
            "reason": str(payload.get("reason") or assessment.rationale),
            "source": "complex",
            "confidence": str(payload.get("confidence") or assessment.confidence),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        registry=registry,
        has_kb=has_kb,
        intent=assessment,
    )


async def _plan_assessment(
    *,
    user_query: str,
    assessment: IntentAssessment,
    has_kb: bool,
    has_routable_kbs: bool,
    registry: AgentRegistry,
    llm_cfg: "UserLLMConfig | None",
    cost: CostTracker,
) -> RouteDecision:
    if not _needs_multi_agent_plan(user_query, assessment) or llm_cfg is None:
        return _plan_from_intent(
            assessment,
            has_kb=has_kb,
            has_routable_kbs=has_routable_kbs,
            registry=registry,
        )
    try:
        return await llm_generate_dag(
            user_query=user_query,
            assessment=assessment,
            has_kb=has_kb,
            registry=registry,
            llm_cfg=llm_cfg,
            cost=cost,
        )
    except Exception:  # noqa: BLE001
        return _plan_from_intent(
            assessment,
            has_kb=has_kb,
            has_routable_kbs=has_routable_kbs,
            registry=registry,
        )


@traced("supervisor_resolve_route")
async def resolve_agent_route(
    *,
    has_kb: bool,
    registry: AgentRegistry,
    user_query: str,
    cost: CostTracker,
    has_routable_kbs: bool = False,
    triage_llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    default_llm_cfg: "UserLLMConfig | None" = None,
    mode: str | None = None,
    pending_refund_followup: bool = False,
    provided_human_inputs: dict[str, str] | None = None,
) -> RouteDecision:
    """Cascade: rule → triage → complex → fallback. Always a validated DAG."""
    settings = get_settings()
    route_mode = normalize_route_mode(mode or getattr(settings, "agent_route_mode", "layered"))

    rule = rule_route(
        has_kb=has_kb,
        has_routable_kbs=has_routable_kbs,
        registry=registry,
        user_query=user_query,
    )
    if pending_refund_followup:
        # A refund can continue from a prior list/select turn as well as from
        # an interrupt resume. Only an exact confirmation can become
        # refund_confirm; an order ID alone must not degrade to order_lookup.
        if not (
            rule is not None
            and str((rule.get("intent") or {}).get("intent") or "") == "refund_confirm"
        ):
            understanding = understand_query(user_query)
            supplied = provided_human_inputs or {}
            missing_slots: list[str] = []
            if not understanding.order_ids and not str(supplied.get("order_id") or "").strip():
                missing_slots.append("order_id")
            if not understanding.refund_reason and not str(supplied.get("refund_reason") or "").strip():
                missing_slots.append("refund_reason")
            return _plan_from_intent(
                IntentAssessment(
                    domain="orders",
                    intent="refund_prepare",
                    risk="write",
                    missing_slots=tuple(missing_slots),
                    confidence="medium",
                    source="rule",
                    rationale="pending_refund_followup",
                ),
                has_kb=has_kb,
                has_routable_kbs=has_routable_kbs,
                registry=registry,
            )
    if rule is not None:
        return rule

    if route_mode == "rule_only":
        return _plan_from_intent(
            fallback_assessment(has_kb=has_kb, has_routable_kbs=has_routable_kbs),
            has_kb=has_kb,
            has_routable_kbs=has_routable_kbs,
            registry=registry,
        )

    async def _run(source: IntentSource, cfg: "UserLLMConfig | None") -> IntentAssessment | None:
        if cfg is None:
            return None
        try:
            return await llm_classify_intent(
                user_query=user_query,
                has_kb=has_kb,
                has_routable_kbs=has_routable_kbs,
                llm_cfg=cfg,
                cost=cost,
                source=source,
            )
        except Exception:  # noqa: BLE001
            return None

    triage_cfg = triage_llm_cfg or default_llm_cfg
    if route_mode in {"rule_triage", "layered"}:
        triage = await _run("triage", triage_cfg)
        if triage is not None and triage.confidence in {"high", "medium"}:
            return await _plan_assessment(
                user_query=user_query,
                assessment=triage,
                has_kb=has_kb,
                has_routable_kbs=has_routable_kbs,
                registry=registry,
                llm_cfg=triage_cfg,
                cost=cost,
            )

    if route_mode == "layered":
        complex_intent = await _run("complex", complex_llm_cfg or default_llm_cfg)
        if complex_intent is not None:
            return await _plan_assessment(
                user_query=user_query,
                assessment=complex_intent,
                has_kb=has_kb,
                has_routable_kbs=has_routable_kbs,
                registry=registry,
                llm_cfg=complex_llm_cfg or default_llm_cfg,
                cost=cost,
            )

    return _plan_from_intent(
        fallback_assessment(has_kb=has_kb, has_routable_kbs=has_routable_kbs),
        has_kb=has_kb,
        has_routable_kbs=has_routable_kbs,
        registry=registry,
    )
