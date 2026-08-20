"""Lossless query understanding and intent/risk classification.

This module deliberately keeps the original user utterance authoritative.  A
retrieval agent may later create a search-oriented rewrite, but execution
routes always use the preserved text and extracted entities.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

IntentDomain = Literal["general", "knowledge", "orders"]
IntentName = Literal[
    "general_chat",
    "knowledge_lookup",
    "order_lookup",
    "refund_prepare",
    "refund_confirm",
    "refund_information",
]
RiskLevel = Literal["none", "read", "write", "confirmation_required"]
IntentSource = Literal["rule", "triage", "complex", "fallback"]

_ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)
_APPROVAL_ID_PATTERN = re.compile(r"\bRFD-[A-Z0-9-]+\b", re.IGNORECASE)
_REFUND_INFO_HINTS = ("退款政策", "退款规则", "退款条款", "退款流程", "退款条件")
_ORDER_LOOKUP_HINTS = ("我的订单", "查订单", "订单信息", "订单详情", "订单号")
_REFUND_HINTS = ("退款", "退货", "退这笔", "退钱", "我要退", "申请退")


@dataclass(frozen=True)
class QueryUnderstanding:
    raw_query: str
    normalized_query: str
    order_ids: tuple[str, ...] = ()
    approval_ids: tuple[str, ...] = ()
    confirmation_text: str | None = None
    refund_reason: str | None = None

    def trace_metadata(self) -> dict[str, Any]:
        # The raw query is already a user-visible chat message.  Do not copy it
        # to trace events; expose only parsed shape and stable IDs.
        return {
            "normalized": self.normalized_query,
            "order_ids": list(self.order_ids),
            "approval_ids": list(self.approval_ids),
            "has_refund_reason": self.refund_reason is not None,
        }


@dataclass(frozen=True)
class IntentAssessment:
    domain: IntentDomain
    intent: IntentName
    risk: RiskLevel
    missing_slots: tuple[str, ...] = ()
    confidence: Literal["high", "medium", "low"] = "low"
    source: IntentSource = "fallback"
    latency_ms: int = 0
    rationale: str = ""

    def trace_metadata(self) -> dict[str, Any]:
        result = asdict(self)
        result["missing_slots"] = list(self.missing_slots)
        return result


def understand_query(query: str) -> QueryUnderstanding:
    """Normalize whitespace and extract immutable execution entities only."""
    raw = query or ""
    normalized = " ".join(raw.split())
    order_ids = tuple(dict.fromkeys(match.upper() for match in _ORDER_ID_PATTERN.findall(normalized)))
    approval_ids = tuple(dict.fromkeys(match.upper() for match in _APPROVAL_ID_PATTERN.findall(normalized)))
    confirmation_text = (
        normalized
        if re.fullmatch(r"确认退款\s+RFD-[A-Z0-9-]+", normalized, flags=re.IGNORECASE)
        else None
    )
    reason: str | None = None
    reason_match = re.search(r"(?:退款原因|原因)\s*(?:是|为|:|：)?\s*(.+)$", normalized)
    if reason_match and reason_match.group(1).strip():
        reason = reason_match.group(1).strip()
    return QueryUnderstanding(
        raw_query=raw,
        normalized_query=normalized,
        order_ids=order_ids,
        approval_ids=approval_ids,
        confirmation_text=confirmation_text,
        refund_reason=reason,
    )


def rule_classify(understanding: QueryUnderstanding) -> IntentAssessment | None:
    """High-confidence, deterministic classification for execution routes."""
    started = time.perf_counter()
    text = understanding.normalized_query
    if understanding.confirmation_text and understanding.approval_ids:
        return IntentAssessment(
            domain="orders",
            intent="refund_confirm",
            risk="confirmation_required",
            confidence="high",
            source="rule",
            latency_ms=int((time.perf_counter() - started) * 1000),
            rationale="exact_refund_confirmation",
        )

    if any(hint in text for hint in _REFUND_HINTS):
        if any(hint in text for hint in _REFUND_INFO_HINTS) and not understanding.order_ids:
            return IntentAssessment(
                domain="knowledge",
                intent="refund_information",
                risk="read",
                confidence="high",
                source="rule",
                latency_ms=int((time.perf_counter() - started) * 1000),
                rationale="refund_information_request",
            )
        missing: list[str] = []
        if not understanding.order_ids:
            missing.append("order_id")
        if not understanding.refund_reason:
            missing.append("refund_reason")
        return IntentAssessment(
            domain="orders",
            intent="refund_prepare",
            risk="write",
            missing_slots=tuple(missing),
            confidence="high",
            source="rule",
            latency_ms=int((time.perf_counter() - started) * 1000),
            rationale="refund_operation",
        )

    if understanding.order_ids or any(hint in text for hint in _ORDER_LOOKUP_HINTS):
        return IntentAssessment(
            domain="orders",
            intent="order_lookup",
            risk="read",
            confidence="high",
            source="rule",
            latency_ms=int((time.perf_counter() - started) * 1000),
            rationale="order_operation",
        )
    return None


def fallback_assessment(*, has_kb: bool, has_routable_kbs: bool) -> IntentAssessment:
    """Conservative non-model fallback when both classifier models are absent."""
    if has_kb or has_routable_kbs:
        return IntentAssessment(
            domain="knowledge",
            intent="knowledge_lookup",
            risk="read",
            confidence="low",
            rationale="kb_fallback",
        )
    return IntentAssessment(
        domain="general",
        intent="general_chat",
        risk="none",
        confidence="low",
        rationale="general_fallback",
    )
