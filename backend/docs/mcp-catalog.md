# MCP capability catalog

`MCP_SERVERS_JSON` describes deployable transports and the Host-reviewed
capabilities exposed to agents. It replaces the local orders Mock compatibility
entry when set. A server's raw `tools/list` result is discovery metadata only:
it never grants an agent access by itself.

## 管理后台发布目录

管理员可在 `/admin/mcp` 保存草稿、测试连接并发布数据库目录。每次发布都会产生不可变的
**PluginSet** 快照（版本和 SHA-256 校验值）；每个 API 副本在编译新对话图前读取当前版本，
而已暂停的审批/检查点会固定解析创建它的旧版本，因此不需要重启也不会在恢复时悄悄换成新
MCP 服务。正在执行的图同样保留原 manager。`MCP_SERVERS_JSON` 仍是没有已发布数据库
目录时的部署级回退，特别是本仓库的本地 orders stdio Mock。

Web 管理面有两个侧边 Tab：`MCP` 是 Codex 风格的连接表单，只管理连接和工具 allowlist；
`受限 MCP` 才把远端工具映射到受审核的业务契约、Agent 与 Host 策略，并负责发布。这样，
保存一个通用 MCP 连接不会自动获得任何 Agent 权限。`streamable_http` 必须使用 HTTPS，开发
环境才允许 `localhost` HTTP；`stdio` 可以填写命令、独立参数、工作目录、显式环境变量和环境
变量传递列表，但只在本地开发/测试环境可保存或测试。生产环境始终拒绝网页 STDIO 配置，必须
由受审核的部署配置或镜像提供。STDIO 子进程不会继承整个 API 环境，只会继承
`inherit_environment` 中列出的变量。密钥以引用名存在 catalog 中，实际值只在提交时写入加密
快照，任何读取接口只返回“该引用是否已配置”。发布前会重新校验插件 Manifest、能力契约、
allowlist、Agent 兼容性、身份注入和 `high_risk_write` 的 Host `policy_id`。运行时在每次 HTTP
MCP 连接前解析地址并拒绝非公网地址（开发环境的 loopback 除外），并禁止重定向。

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
`commerce.refund.prepare@v1` 和 `commerce.refund.confirm@v1`。管理端发现到的未知工具
只会显示为候选项，不能直接授予 `orders` Agent；它需要先由插件开发者声明契约和兼容
Agent，再通过发布验证。数据库发布只接受声明性 HTTP adapter 配置，不能上传或执行任意
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
