"""Small deterministic boundary between the chat runtime and order workflow.

Order/refund operations are deliberately *not* selected by an LLM planner.
The ordinary conversation runtime remains a single ReAct loop; only this
high-risk capability is routed to its dedicated approval workflow.
"""
from __future__ import annotations

from typing import Any

from src.harness.orchestration.intent import rule_classify, understand_query


def _latest_user_text(messages: list[dict[str, Any]] | None) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _continues_refund_workflow(messages: list[dict[str, Any]] | None) -> bool:
    """Keep a requested refund slot-fill turn in the deterministic workflow.

    This is intentionally narrow: an earlier assistant response must have
    explicitly requested a refund reason or confirmation.  A random later
    message such as "because it is slow" must not gain order-tool access.
    """
    seen_current_user = False
    for message in reversed(messages or []):
        role = message.get("role")
        if role == "user" and not seen_current_user:
            seen_current_user = True
            continue
        if seen_current_user and role == "assistant":
            content = message.get("content")
            text = content if isinstance(content, str) else ""
            return "退款" in text and any(
                marker in text for marker in ("退款原因", "确认退款", "待确认")
            )
    return False


def requires_order_workflow(messages: list[dict[str, Any]] | None) -> bool:
    """Return true only for a deterministic order/refund workflow turn."""
    assessment = rule_classify(understand_query(_latest_user_text(messages)))
    return bool(assessment is not None and assessment.domain == "orders") or _continues_refund_workflow(messages)
