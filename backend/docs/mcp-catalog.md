# MCP capability catalog

`MCP_SERVERS_JSON` describes deployable transports and the Host-reviewed
capabilities exposed to agents. It replaces the local orders Mock compatibility
entry when set. A server's raw `tools/list` result is discovery metadata only:
it never grants an agent access by itself.

```json
{
  "servers": [
    {
      "id": "orders",
      "transport": "streamable_http",
      "endpoint": "https://orders-mcp.internal/mcp",
      "allowed_tools": ["list_orders", "prepare_refund", "confirm_refund"],
      "identity_argument": "actor_id",
      "secret_headers": {"Authorization": "orders_bearer"},
      "timeout_seconds": 12
    }
  ],
  "capabilities": [
    {
      "id": "commerce.orders.list",
      "server_id": "orders",
      "tool_name": "list_orders",
      "exposed_name": "list_orders",
      "agent_id": "orders",
      "risk": "read",
      "description": "查询当前登录用户的订单列表。",
      "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
      "id": "commerce.refund.confirm",
      "server_id": "orders",
      "tool_name": "confirm_refund",
      "exposed_name": "confirm_refund",
      "agent_id": "orders",
      "risk": "high_risk_write",
      "policy_id": "refund_confirmation_v1",
      "description": "执行已确认的退款。",
      "input_schema": {
        "type": "object",
        "properties": {
          "approval_id": {"type": "string"},
          "confirmation_text": {"type": "string"}
        },
        "required": ["approval_id", "confirmation_text"]
      }
    }
  ]
}
```

Keep the catalog reviewable and secret-free. Put values referenced by
`secret_arguments` and `secret_headers` in `MCP_SECRETS_JSON`, for example:

```json
{"orders_bearer":"Bearer deployment-secret"}
```

The runtime opens one initialized connection per enabled server, runs MCP tool
discovery through its `allowed_tools` allowlist, and rebuilds each agent's tool
registry from the capability bindings. Identity and secrets are Host-injected;
model-generated arguments trying to set those fields are rejected. Connection
failures invalidate the connection but do not replay an MCP request, which is
important for writes. `policy_id` and the human-confirmation gate remain
Host-owned policy: a server cannot mark its own refund tool safe.
Every `high_risk_write` capability must name an implemented Host `policy_id`;
an unknown policy is blocked before the MCP request is sent.
