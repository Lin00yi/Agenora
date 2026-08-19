"""Three-layer supervisor router: rule → triage → complex.

Layer 1 (rule): high-confidence deterministic intents only.
Layer 2 (triage): small/fast model for ordinary ambiguous queries.
Layer 3 (complex): larger model when triage is low-confidence or the query
looks multi-intent / long / structurally complex.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal, TypedDict, TYPE_CHECKING

from src.agent.nodes.constants import (
    _RULE_INFORMATION_SEEKING_HINTS,
    _RULE_MULTI_INTENT_KEYWORDS,
    _RULE_SKIP_KEYWORDS,
)
from src.agent.registry import AgentRegistry
from src.infra.llm import CostTracker, get_client, pick_model, with_cache_control
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


class RouteDecision(TypedDict):
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


def fallback_route(*, has_kb: bool, registry: AgentRegistry) -> RouteDecision:
    available = registry.available(has_kb=has_kb)
    if has_kb and "rag" in available:
        return {
            "target": "rag",
            "reason": "kb_bound_default",
            "source": "fallback",
            "confidence": "medium",
            "latency_ms": 0,
        }
    if "chat" in available:
        return {
            "target": "chat",
            "reason": "unbound_default",
            "source": "fallback",
            "confidence": "high",
            "latency_ms": 0,
        }
    if available:
        return {
            "target": available[0],
            "reason": "first_available",
            "source": "fallback",
            "confidence": "low",
            "latency_ms": 0,
        }
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
            return {
                "target": "chat",
                "reason": "unbound_default",
                "source": "rule",
                "confidence": "high",
                "latency_ms": 0,
            }
        return None

    if "chat" not in available and "rag" not in available:
        return None

    if not text:
        # Empty after sanitize — stay on rag when KB is bound so empty handling
        # remains inside the KB subgraph.
        if "rag" in available:
            return {
                "target": "rag",
                "reason": "empty_query_kb_bound",
                "source": "rule",
                "confidence": "high",
                "latency_ms": 0,
            }
        return None

    if "chat" in available:
        if any(keyword in text for keyword in _RULE_SKIP_KEYWORDS):
            return {
                "target": "chat",
                "reason": "kb_bound_non_kb_intent",
                "source": "rule",
                "confidence": "high",
                "latency_ms": 0,
            }
        if len(text) <= 8 and not any(
            mark in text for mark in ("?", "？", "吗", "么", "如何", "怎么")
        ):
            if text in {"你好", "您好", "在吗", "早上好", "晚安", "谢谢", "多谢"}:
                return {
                    "target": "chat",
                    "reason": "kb_bound_chitchat",
                    "source": "rule",
                    "confidence": "high",
                    "latency_ms": 0,
                }

    # Clear private-KB fact seeking: still escalate — product names alone are
    # ambiguous, and triage/complex own the grey zone. Rules stay conservative.
    _ = _RULE_INFORMATION_SEEKING_HINTS
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
    available: list[str],
    source: RouteSource,
    latency_ms: int,
) -> RouteDecision:
    if not isinstance(payload, dict):
        raise ValueError("router payload must be an object")
    target = str(payload.get("target") or "").strip().lower()
    if target not in _ROUTE_TARGETS or target not in available:
        raise ValueError(f"invalid target: {target}")
    confidence_raw = str(payload.get("confidence") or "medium").strip().lower()
    confidence: RouteConfidence = (
        confidence_raw if confidence_raw in _ROUTE_CONFIDENCE else "medium"  # type: ignore[assignment]
    )
    reason = str(payload.get("reason") or f"{source}_route").strip() or f"{source}_route"
    return {
        "target": target,
        "reason": reason[:80],
        "source": source,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }


def _router_system_prompt(*, has_kb: bool, available: list[str], layer: RouteSource) -> str:
    targets = ", ".join(available)
    kb_line = (
        "当前会话已绑定私有知识库。涉及产品事实、流程、政策、费用、故障排查时优先 rag；"
        "闲聊、翻译、润色、总结刚才回答、与 KB 无关的通用写作走 chat。"
        if has_kb
        else "当前未绑定知识库，只能选择 chat。"
    )
    depth = (
        "你是快速意图分流器（triage）。只做粗分，拿不准时把 confidence 设为 low。"
        if layer == "triage"
        else "你是复杂意图路由器。仔细区分多意图、含糊指代与是否需要私有知识库。"
    )
    return (
        f"{depth}\n"
        f"{kb_line}\n"
        f"只能从这些 target 中选择：{targets}\n"
        "只输出 JSON，不要解释。\n"
        '格式：{"target":"chat"|"rag","confidence":"high"|"medium"|"low","reason":"short_snake"}\n'
        "reason 必须是短 snake_case，优先使用："
        "needs_kb_fact / chitchat / general_chat / web_needed / multi_intent / non_kb。"
        "不要写长句，不要写 query_about_xxx。\n"
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
    """Ask one model layer for a structured route decision."""
    start = time.perf_counter()
    available = registry.available(has_kb=has_kb)
    if not available:
        raise RuntimeError("agent registry is empty")
    if len(available) == 1:
        return {
            "target": available[0],
            "reason": "single_available",
            "source": source,
            "confidence": "high",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }

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
                max_tokens=256,
            )
            cost.add(model, getattr(resp, "usage", None), cfg=llm_cfg)
            text = resp.choices[0].message.content or ""
            if gen is not None:
                gen.update(output=text, usage=getattr(resp, "usage", None))
        else:
            resp = await client.messages.create(
                model=model,
                max_tokens=256,
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
        available=available,
        source=source,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )


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
    """Cascade: rule → triage → complex → fallback."""
    settings = get_settings()
    route_mode = normalize_route_mode(mode or getattr(settings, "agent_route_mode", "layered"))

    rule = rule_route(has_kb=has_kb, registry=registry, user_query=user_query)
    if rule is not None:
        return rule

    if route_mode == "rule_only":
        return fallback_route(has_kb=has_kb, registry=registry)

    complex_query = looks_complex_query(user_query)
    triage_cfg = triage_llm_cfg or default_llm_cfg
    # Complex layer prefers an explicit complex profile; otherwise reuse default.
    complex_cfg = complex_llm_cfg or (
        default_llm_cfg if complex_llm_cfg is None and complex_query else None
    )

    # Clearly complex: escalate to layer 3 after rules (skip weak triage).
    if (
        route_mode == "layered"
        and complex_query
        and complex_cfg is not None
    ):
        try:
            return await llm_route(
                user_query=user_query,
                has_kb=has_kb,
                registry=registry,
                llm_cfg=complex_cfg,
                cost=cost,
                source="complex",
            )
        except Exception:  # noqa: BLE001
            return fallback_route(has_kb=has_kb, registry=registry)

    if route_mode in {"rule_triage", "layered"} and triage_cfg is not None:
        try:
            triage = await llm_route(
                user_query=user_query,
                has_kb=has_kb,
                registry=registry,
                llm_cfg=triage_cfg,
                cost=cost,
                source="triage",
            )
        except Exception:  # noqa: BLE001
            triage = None

        if triage is not None and triage["confidence"] in {"high", "medium"}:
            return triage

        if route_mode == "layered" and (complex_llm_cfg or default_llm_cfg) is not None:
            escalate_cfg = complex_llm_cfg or default_llm_cfg
            try:
                return await llm_route(
                    user_query=user_query,
                    has_kb=has_kb,
                    registry=registry,
                    llm_cfg=escalate_cfg,
                    cost=cost,
                    source="complex",
                )
            except Exception:  # noqa: BLE001
                if triage is not None:
                    return triage
                return fallback_route(has_kb=has_kb, registry=registry)

        if triage is not None:
            return triage

    if route_mode == "layered" and (complex_llm_cfg or default_llm_cfg) is not None:
        try:
            return await llm_route(
                user_query=user_query,
                has_kb=has_kb,
                registry=registry,
                llm_cfg=complex_llm_cfg or default_llm_cfg,
                cost=cost,
                source="complex",
            )
        except Exception:  # noqa: BLE001
            pass

    return fallback_route(has_kb=has_kb, registry=registry)
