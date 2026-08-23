"""Human-in-the-loop gates for the orders execution graph."""
from __future__ import annotations

import json
from typing import Any

from langgraph.types import interrupt

from src.harness.contracts.state import AgentState
from src.harness.mcp.orders import list_refundable_order_options
from src.harness.orchestration.intent import rule_classify, understand_query


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages") or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def extract_pending_confirmation(tool_log: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Read only the structured prepare-refund result needed for the gate."""
    for entry in reversed(tool_log or []):
        if entry.get("name") != "prepare_refund" or entry.get("error"):
            continue
        raw = entry.get("result")
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("status") == "awaiting_confirmation":
            phrase = payload.get("confirmation_phrase")
            approval_id = payload.get("approval_id")
            if isinstance(phrase, str) and isinstance(approval_id, str):
                return {
                    "approval_id": approval_id,
                    "confirmation_phrase": phrase,
                    "order_id": payload.get("order_id"),
                    "amount_minor": payload.get("amount_minor"),
                    "currency": payload.get("currency"),
                    "refund_to": payload.get("refund_to"),
                    "product_name": payload.get("product_name"),
                    "product_url": payload.get("product_url"),
                    "order_status_label": payload.get("order_status_label"),
                }
    return None


def human_slot_prompt(slot: str, confirmation: dict[str, Any] | None = None) -> str:
    if slot == "order_id":
        return "请选择要退款的订单。"
    if slot == "refund_reason":
        return "请填写退款原因。"
    if slot == "refund_confirmation" and confirmation is not None:
        return (
            f"退款确认单 {confirmation['approval_id']} 已创建。"
            f"请单独确认：{confirmation['confirmation_phrase']}"
        )
    return "请补充继续处理所需的信息。"


def _merge_inputs_from_message(state: AgentState, inputs: dict[str, str]) -> dict[str, str]:
    """Fill slots already present in the latest user turn."""
    understanding = understand_query(_latest_user_text(state))
    merged = dict(inputs)
    if understanding.order_ids and not merged.get("order_id"):
        merged["order_id"] = understanding.order_ids[0]
    if understanding.refund_reason and not merged.get("refund_reason"):
        merged["refund_reason"] = understanding.refund_reason
    if understanding.confirmation_text and not merged.get("refund_confirmation"):
        merged["refund_confirmation"] = understanding.confirmation_text
    return merged


def resolve_required_slots(state: AgentState) -> list[str]:
    confirmation = state.get("pending_confirmation")
    if isinstance(confirmation, dict):
        return ["refund_confirmation"]

    required = list(state.get("human_required_slots") or [])
    if not required:
        assessment = rule_classify(understand_query(_latest_user_text(state)))
        if assessment is not None and assessment.domain == "orders" and assessment.intent == "refund_prepare":
            required = list(assessment.missing_slots)

    inputs = _merge_inputs_from_message(state, dict(state.get("human_inputs") or {}))
    return [slot for slot in required if not str(inputs.get(slot) or "").strip()]


def needs_human_gate(state: AgentState) -> bool:
    return bool(resolve_required_slots(state))


async def human_input_gate(state: AgentState, *, user_id: str | None) -> AgentState:
    """Pause the graph until each required human field is supplied."""
    confirmation = state.get("pending_confirmation")
    required: list[str]
    if isinstance(confirmation, dict):
        required = ["refund_confirmation"]
    else:
        assessment = rule_classify(understand_query(_latest_user_text(state)))
        required = list(state.get("human_required_slots") or [])
        if not required and assessment is not None and assessment.intent == "refund_prepare":
            required = list(assessment.missing_slots)

    inputs = _merge_inputs_from_message(state, dict(state.get("human_inputs") or {}))
    remaining = [slot for slot in required if not str(inputs.get(slot) or "").strip()]
    if not remaining:
        return {
            **state,
            "human_inputs": inputs,
            "human_required_slots": required,
            "human_gate_resumed": bool(required),
        }

    slot = remaining[0]
    order_options = (
        await list_refundable_order_options(user_id=user_id) if slot == "order_id" else []
    )
    active_confirmation = confirmation if isinstance(confirmation, dict) else None
    answer = interrupt(
        {
            "kind": "human_input_required",
            "slot": slot,
            "required_slots": remaining,
            "prompt": human_slot_prompt(slot, active_confirmation),
            "approval_id": active_confirmation.get("approval_id") if active_confirmation else None,
            "confirmation_phrase": active_confirmation.get("confirmation_phrase") if active_confirmation else None,
            "order_id": active_confirmation.get("order_id") if active_confirmation else None,
            "amount_minor": active_confirmation.get("amount_minor") if active_confirmation else None,
            "currency": active_confirmation.get("currency") if active_confirmation else None,
            "refund_to": active_confirmation.get("refund_to") if active_confirmation else None,
            "product_name": active_confirmation.get("product_name") if active_confirmation else None,
            "product_url": active_confirmation.get("product_url") if active_confirmation else None,
            "order_status_label": active_confirmation.get("order_status_label") if active_confirmation else None,
            "order_options": order_options,
        }
    )
    value = answer.get("value") or answer.get(slot) or "" if isinstance(answer, dict) else answer
    text = str(value or "").strip()
    inputs[slot] = text
    messages = list(state.get("messages") or [])
    messages.append({"role": "user", "content": text})
    return {
        **state,
        "messages": messages,
        "human_inputs": inputs,
        "human_required_slots": required,
        "human_gate_resumed": True,
        "pending_confirmation": None if slot == "refund_confirmation" else confirmation,
    }


async def sync_pending_confirmation(state: AgentState) -> AgentState:
    pending = extract_pending_confirmation(state.get("tool_call_log"))
    if pending is None:
        return state
    return {**state, "pending_confirmation": pending}
