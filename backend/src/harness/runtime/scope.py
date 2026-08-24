"""Runtime-scope resolution for the default constrained ReAct agent.

This module intentionally decides *capabilities*, not agents or a task DAG.
It keeps the established rule -> triage -> complex -> fallback cascade, then
admits a knowledge-base capability only for a knowledge-scoped turn.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal, TYPE_CHECKING

from src.capabilities.knowledge.application.routing import (
    AutoKBRoute,
    resolve_auto_kb_route_from_candidates,
)
from src.harness.orchestration.intent import (
    IntentAssessment,
    fallback_assessment,
    rule_classify,
    understand_query,
)
from src.platform.llm import CostTracker, get_client, pick_model, with_cache_control
from src.platform.observability import ageneration, traced

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig


ScopeKind = Literal["general", "knowledge_base", "orders"]
ScopeSource = Literal["rule", "triage", "complex", "fallback", "pinned"]
ScopeConfidence = Literal["high", "medium", "low"]
ScopeMode = Literal["rule_only", "rule_triage", "layered"]
_SCOPE_MODES = frozenset({"rule_only", "rule_triage", "layered"})


@dataclass(frozen=True)
class RuntimeScope:
    """The ACL-safe capabilities available to one ReAct turn."""

    kind: ScopeKind
    intent: IntentAssessment
    selected_kbs: tuple[Any, ...] = ()
    kb_route: AutoKBRoute | None = None
    intent_cost_usd: float | None = 0.0

    @property
    def source(self) -> ScopeSource:
        if self.kb_route is not None:
            return self.kb_route.source  # type: ignore[return-value]
        return self.intent.source  # type: ignore[return-value]

    @property
    def confidence(self) -> ScopeConfidence:
        if self.kb_route is not None:
            return self.kb_route.confidence  # type: ignore[return-value]
        return self.intent.confidence

    @property
    def latency_ms(self) -> int:
        return self.intent.latency_ms + (self.kb_route.latency_ms if self.kb_route else 0)

    @property
    def cost_usd(self) -> float | None:
        route_cost = self.kb_route.cost_usd if self.kb_route else 0.0
        if self.intent_cost_usd is None or route_cost is None:
            return None
        return float(self.intent_cost_usd) + float(route_cost)

    def trace_metadata(self) -> dict[str, Any]:
        selected_ids = [str(kb.id) for kb in self.selected_kbs]
        return {
            "kind": self.kind,
            "intent": asdict(self.intent),
            "selected_kb_ids": selected_ids,
            "source": self.source,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "kb_route": self.kb_route.trace_metadata() if self.kb_route else None,
        }


def normalize_scope_mode(raw: str | None) -> ScopeMode:
    mode = (raw or "layered").strip().lower()
    return mode if mode in _SCOPE_MODES else "layered"  # type: ignore[return-value]


def _needs_complex_intent_layer(
    assessment: IntentAssessment | None,
    *,
    scope_mode: ScopeMode,
) -> bool:
    """Return True when layered mode should escalate past triage to the complex LLM pass."""
    if scope_mode != "layered":
        return False
    if assessment is None:
        return True
    # Triage (or rule) high/medium confidence is sufficient — skip the second LLM call.
    if assessment.confidence in {"high", "medium"}:
        return False
    return assessment.confidence == "low"


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            text = message["content"].strip()
            if text:
                return text
    return ""


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty runtime scope response")
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found in runtime scope response") from None
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("runtime scope payload must be an object")
    return payload


def _coerce_assessment(payload: dict[str, Any], *, source: ScopeSource, latency_ms: int) -> IntentAssessment:
    domain = str(payload.get("domain") or "general").strip().lower()
    intent = str(payload.get("intent") or "general_chat").strip().lower()
    risk = str(payload.get("risk") or "none").strip().lower()
    confidence = str(payload.get("confidence") or "low").strip().lower()
    if domain not in {"general", "knowledge", "orders"}:
        raise ValueError("invalid scope domain")
    if intent not in {
        "general_chat", "knowledge_lookup", "order_lookup", "refund_prepare",
        "refund_confirm", "refund_information",
    }:
        raise ValueError("invalid scope intent")
    if risk not in {"none", "read", "write", "confirmation_required"}:
        raise ValueError("invalid scope risk")
    slots = payload.get("missing_slots") or []
    if not isinstance(slots, list):
        slots = []
    missing = tuple(str(slot).strip() for slot in slots if str(slot).strip() in {"order_id", "refund_reason", "approval_id"})
    return IntentAssessment(
        domain=domain,  # type: ignore[arg-type]
        intent=intent,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        missing_slots=missing,
        confidence=confidence if confidence in {"high", "medium", "low"} else "low",  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        rationale=str(payload.get("rationale") or intent)[:80],
    )


@traced("runtime_scope.intent")
async def _classify_with_llm(
    *,
    query: str,
    has_bound_kb: bool,
    has_routable_kbs: bool,
    llm_cfg: "UserLLMConfig | None",
    source: Literal["triage", "complex"],
) -> tuple[IntentAssessment | None, float | None]:
    started = time.perf_counter()
    model = pick_model([{"role": "user", "content": query}], [], llm_cfg)
    prompt = (
        f"你是{'轻量' if source == 'triage' else '高精度'}运行范围识别器，不是规划器。只输出 JSON："
        '{"domain":"general|knowledge|orders","intent":"general_chat|knowledge_lookup|order_lookup|refund_prepare|refund_confirm|refund_information",'
        '"risk":"none|read|write|confirmation_required","missing_slots":["order_id|refund_reason|approval_id"],'
        '"confidence":"high|medium|low","rationale":"short_snake_case"}。'
        "订单查询是 orders/order_lookup/read；退款申请是 orders/refund_prepare/write；"
        "只有精确确认退款是 refund_confirm/confirmation_required；退款政策是 knowledge/refund_information/read。"
        f"当前已固定知识库={has_bound_kb}；有可访问候选知识库={has_routable_kbs}。"
        "拿不准必须返回 low，不能输出 agent、tasks、工具或解释。"
    )
    client = get_client(llm_cfg)
    tracker = CostTracker()
    from src.settings import get_settings

    is_anthropic = llm_cfg.provider == "anthropic" if llm_cfg is not None else get_settings().llm_provider == "anthropic"
    async with ageneration(f"runtime_scope.intent.{source}", model=model, input={"has_bound_kb": has_bound_kb, "has_routable_kbs": has_routable_kbs}) as generation:
        if is_anthropic:
            response = await client.messages.create(
                model=model,
                max_tokens=256,
                system=with_cache_control([{"type": "text", "text": prompt}], llm_cfg),
                messages=[{"role": "user", "content": query}],
            )
            tracker.add(model, response.usage, cfg=llm_cfg)
            text = "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            usage = response.usage
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": query}],
                max_tokens=256,
            )
            usage = getattr(response, "usage", None)
            tracker.add(model, usage, cfg=llm_cfg)
            text = response.choices[0].message.content or ""
        if generation is not None:
            generation.update(output=text, usage=usage)
    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        if not (text or "").strip():
            return None, tracker.total_usd
        return (
            _coerce_assessment(_extract_json_object(text), source=source, latency_ms=latency_ms),
            tracker.total_usd,
        )
    except (json.JSONDecodeError, ValueError):
        # Expected provider/format drift — caller falls through to complex/fallback.
        return None, tracker.total_usd


@traced("runtime_scope")
async def resolve_runtime_scope(
    *,
    messages: list[dict[str, Any]],
    bound_kb: Any | None,
    candidates: list[Any],
    llm_cfg: "UserLLMConfig | None",
    triage_llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    mode: str | None = None,
) -> RuntimeScope:
    """Resolve a single turn's capability scope before entering ReAct."""
    query = _latest_user_text(messages)
    has_bound_kb = bound_kb is not None
    has_routable_kbs = bool(candidates)
    rule = rule_classify(understand_query(query)) if query else None
    scope_mode = normalize_scope_mode(mode)
    assessment = rule
    intent_cost_usd: float | None = 0.0
    if assessment is None and scope_mode in {"rule_triage", "layered"}:
        try:
            assessment, intent_cost_usd = await _classify_with_llm(
                query=query,
                has_bound_kb=has_bound_kb,
                has_routable_kbs=has_routable_kbs,
                llm_cfg=triage_llm_cfg or llm_cfg,
                source="triage",
            )
        except Exception:  # noqa: BLE001 - continue to the stronger/fallback layer
            assessment = None
    if _needs_complex_intent_layer(assessment, scope_mode=scope_mode):
        try:
            assessment, complex_cost_usd = await _classify_with_llm(
                query=query,
                has_bound_kb=has_bound_kb,
                has_routable_kbs=has_routable_kbs,
                llm_cfg=complex_llm_cfg or llm_cfg,
                source="complex",
            )
            if intent_cost_usd is None or complex_cost_usd is None:
                intent_cost_usd = None
            else:
                intent_cost_usd += complex_cost_usd
        except Exception:  # noqa: BLE001 - the deterministic fallback remains safe
            assessment = None
    if assessment is None:
        # Capability admission is fail-closed: merely having readable KBs
        # must not grant KB tools to an otherwise unclassified turn.
        assessment = fallback_assessment(has_kb=has_bound_kb, has_routable_kbs=False)

    if assessment.domain == "orders":
        return RuntimeScope(kind="orders", intent=assessment, intent_cost_usd=intent_cost_usd)
    if bound_kb is not None:
        return RuntimeScope(
            kind="knowledge_base", intent=assessment, selected_kbs=(bound_kb,), intent_cost_usd=intent_cost_usd
        )
    if assessment.domain != "knowledge" or not candidates:
        return RuntimeScope(kind="general", intent=assessment, intent_cost_usd=intent_cost_usd)

    # KB selection is now a conditional part of RuntimeScope, never an
    # unconditional pre-ReAct LLM call for ordinary conversation.
    route = await resolve_auto_kb_route_from_candidates(
        messages=messages,
        candidates=candidates,
        llm_cfg=complex_llm_cfg or llm_cfg,
    )
    selected = tuple(route.selected_kbs) if route.needs_retrieval else ()
    return RuntimeScope(
        kind="knowledge_base" if selected else "general",
        intent=assessment,
        selected_kbs=selected,
        kb_route=route,
        intent_cost_usd=intent_cost_usd,
    )
