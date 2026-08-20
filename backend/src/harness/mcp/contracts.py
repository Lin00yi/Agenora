"""Host-owned business contracts for pluggable MCP capabilities.

MCP tool names describe a transport implementation.  Agents must instead
depend on stable, versioned business contracts so a provider can be replaced
without changing prompts, policies, or durable workflows.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

McpRisk = Literal["read", "write", "high_risk_write"]


class CapabilityContract(BaseModel):
    """A versioned, host-reviewed capability interface.

    A plugin release may declare additional contracts, but the Host validates
    the risk, policy and agent compatibility before a binding is published.
    """

    id: str = Field(min_length=3, max_length=160)
    version: int = Field(default=1, ge=1, le=1000)
    plugin_id: str | None = Field(default=None, min_length=3, max_length=120)
    plugin_version: int = Field(default=1, ge=1, le=1000)
    # Stable, Agent-visible tool name. It is deliberately independent from
    # the MCP provider's tool name in ``CapabilityBinding``.
    agent_tool_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    agent_ids: list[str] = Field(min_length=1)
    risk: McpRisk = "read"
    policy_id: str | None = None
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    output_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned or " " in cleaned:
            raise ValueError("contract id must be a non-empty dotted identifier")
        return cleaned

    @field_validator("agent_ids")
    @classmethod
    def _normalise_agents(cls, value: list[str]) -> list[str]:
        values = list(dict.fromkeys(agent.strip() for agent in value if agent.strip()))
        if not values:
            raise ValueError("contract requires at least one compatible agent")
        return values

    @property
    def key(self) -> str:
        return f"{self.id}@v{self.version}"

    @property
    def exposed_name(self) -> str:
        return self.agent_tool_name or self.id.replace(".", "_")


def _schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def builtin_contracts() -> list[CapabilityContract]:
    """Contracts supplied by the trusted built-in orders plugin.

    These live in one source of truth.  The local mock MCP and any remote
    replacement must adapt to them instead of teaching the orders graph a
    new transport tool name.
    """

    common = {"agent_ids": ["orders"]}
    return [
        CapabilityContract(
            id="commerce.orders.list", description="查询当前用户订单", plugin_id="builtin.orders", agent_tool_name="list_orders", **common
        ),
        CapabilityContract(
            id="commerce.orders.get",
            description="按订单号查询当前用户订单",
            plugin_id="builtin.orders",
            agent_tool_name="get_order",
            input_schema=_schema({"order_id": {"type": "string", "description": "订单号"}}, ["order_id"]),
            **common,
        ),
        CapabilityContract(
            id="commerce.refunds.list", description="查询当前用户退款记录", plugin_id="builtin.orders", agent_tool_name="list_refunds", **common
        ),
        CapabilityContract(
            id="commerce.refunds.get",
            description="按退款单号查询退款状态",
            plugin_id="builtin.orders",
            agent_tool_name="get_refund",
            input_schema=_schema({"refund_id": {"type": "string", "description": "退款单号或确认单号"}}, ["refund_id"]),
            **common,
        ),
        CapabilityContract(
            id="commerce.refund.prepare",
            description="创建退款确认单，不执行退款",
            plugin_id="builtin.orders",
            agent_tool_name="prepare_refund",
            risk="write",
            policy_id="refund_v1",
            input_schema=_schema(
                {
                    "order_id": {"type": "string", "description": "订单号"},
                    "reason": {"type": "string", "description": "退款原因"},
                    "amount_minor": {"type": "integer", "description": "退款金额，单位分"},
                },
                ["order_id", "reason"],
            ),
            **common,
        ),
        CapabilityContract(
            id="commerce.refund.confirm",
            description="执行已经明确确认的退款",
            plugin_id="builtin.orders",
            agent_tool_name="confirm_refund",
            risk="high_risk_write",
            policy_id="refund_confirmation_v1",
            input_schema=_schema(
                {
                    "approval_id": {"type": "string", "description": "待确认退款单号"},
                    "confirmation_text": {"type": "string", "description": "精确确认文本"},
                },
                ["approval_id", "confirmation_text"],
            ),
            **common,
        ),
    ]


def contract_index(contracts: list[CapabilityContract]) -> dict[str, CapabilityContract]:
    indexed: dict[str, CapabilityContract] = {}
    for contract in contracts:
        previous = indexed.get(contract.key)
        if previous is not None and previous != contract:
            raise ValueError("capability contract id and version pairs must be unique")
        indexed[contract.key] = contract
    return indexed
