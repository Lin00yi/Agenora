# MCP capability catalog

`MCP_SERVERS_JSON` describes deployable transports and the Host-reviewed
capabilities exposed to agents. It replaces the local orders Mock compatibility
entry when set. A server's raw `tools/list` result is discovery metadata only:
it never grants an agent access by itself.

## 部署级目录

MCP 不提供设置页、后台页面或管理 API。运行时目录仅由 `MCP_SERVERS_JSON` 和
`MCP_SECRETS_JSON`（或内置本地 orders Mock）在部署时提供；改动后需要重启后端。服务端配置
连接与工具 allowlist，能力绑定则把远端工具映射到受审核的业务契约、Agent 与 Host 策略。
因此一个 MCP server 不会仅因发现到工具就自动获得 Agent 权限。

生产 HTTP MCP 必须使用 HTTPS；STDIO 由受审核的镜像或部署配置提供。STDIO 子进程不会继承
整个 API 环境，只会继承 `inherit_environment` 中列出的变量。密钥以引用名存在 catalog 中，
实际值来自 `MCP_SECRETS_JSON` 或部署环境。运行时会校验插件 Manifest、能力契约、allowlist、
Agent 兼容性、身份注入和 `high_risk_write` 的 Host `policy_id`，并在每次 HTTP MCP 连接前拒绝
非公网地址（开发环境 loopback 除外）及重定向。

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
`secret_arguments`、`secret_headers` and `secret_environment` in
`MCP_SECRETS_JSON`, for example:

```json
{"orders_bearer":"Bearer deployment-secret"}
```

## Plugin Manifest 与能力契约

服务、工具名和 Agent 不是同一个概念。一个 `plugins[]` Manifest 声明某个受审核的
adapter release 提供哪些 `contracts[]`；每个 contract 固定 `id@version`、输入/输出
Schema、风险、Host policy 与可兼容的 Agent；最后 `capabilities[]` 才把这个 contract
适配到某个 MCP server 的 `tool_name`。因此替换订单供应商时只需要更新 binding，不需要
让订单图认识供应商的工具名。

内置订单插件的 contract 包括 `commerce.orders.list@v1`、
`commerce.refund.prepare@v1` 和 `commerce.refund.confirm@v1`。未知工具不能直接授予
`orders` Agent；它需要先在部署目录中声明契约和兼容 Agent。目录不支持上传或执行任意
Python/stdio 代码。

The runtime opens one initialized connection per enabled server, runs MCP tool
discovery through its `allowed_tools` allowlist, and rebuilds each agent's tool
registry from contract-backed capability bindings. Discovery is not authority:
every bound capability must reference a versioned contract declared by a plugin
Manifest, and that contract must explicitly allow the target Agent. Identity
and secrets are Host-injected; model-generated arguments trying to set those
fields are rejected. MCP structured responses are checked against the contract
output envelope. Connection failures invalidate the connection but do not
replay an MCP request, which is important for writes. `policy_id` and the
human-confirmation gate remain Host-owned policy: a plugin cannot mark its own
refund tool safe.
Every `high_risk_write` capability must name an implemented Host `policy_id`;
an unknown policy is blocked before the MCP request is sent.
