from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.api.routes.conversations import _completed_refund_report, _stale_refund_confirmation
from src.capabilities.conversations.models import Message


def _message(*, role: str, content: str = "", tools: list[dict] | None = None) -> Message:
    return Message(
        id="00000000-0000-0000-0000-000000000001",
        conversation_id="00000000-0000-0000-0000-000000000002",
        role=role,
        content=content,
        tool_call_log=json.dumps(tools) if tools is not None else None,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=11),
    )


def test_stale_refund_recovery_requires_prior_server_issued_confirmation() -> None:
    approval_id = "RFD-TEST-1"
    human_interrupt = _message(
        role="assistant",
        tools=[
            {
                "name": "human_input_required",
                "input": {"slot": "refund_confirmation", "approval_id": approval_id},
            }
        ],
    )
    exact_confirmation = _message(role="user", content=f"确认退款 {approval_id}")

    recovered = _stale_refund_confirmation([human_interrupt, exact_confirmation])

    assert recovered is not None
    assert recovered[1] == approval_id
    assert _stale_refund_confirmation([human_interrupt, _message(role="user", content="确认退款 RFD-OTHER")]) is None


def test_recovered_refund_report_is_deterministic() -> None:
    assert _completed_refund_report(
        {
            "order_id": "ORD-TEST-1001",
            "refund_no": "RFN-TEST-1",
            "amount_minor": 12900,
            "refund_to": "微信支付",
            "estimated_arrival_at": "2026-08-20T10:00:00+00:00",
        }
    ) == "退款申请已提交。\n订单：ORD-TEST-1001\n退款单号：RFN-TEST-1\n退款金额：12900 分\n退款去向：微信支付\n预计到账：2026-08-20T10:00:00+00:00"
