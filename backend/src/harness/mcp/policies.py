"""Host-owned policy registry for irreversible MCP capabilities."""
from __future__ import annotations

SUPPORTED_HIGH_RISK_POLICIES = frozenset({"refund_confirmation_v1"})


def supports_high_risk_policy(policy_id: str | None) -> bool:
    return bool(policy_id and policy_id in SUPPORTED_HIGH_RISK_POLICIES)
