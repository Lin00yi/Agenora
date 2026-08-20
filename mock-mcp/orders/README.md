# Mock Orders MCP

用于本地开发和自动化测试的 stdio MCP 服务。它拥有自己的模拟订单 SQLite 数据，不属于 `backend` 业务代码。

由 Agenora Host 通过 `backend/src/harness/mcp/orders.py` 按工具调用启动。Host 使用本项目的 `uv.lock` 创建/复用独立环境，不会把 `backend` 的源码路径注入给服务：

```bash
uv run --directory mock-mcp/orders python -m mock_orders_mcp.server
```

运行时需要由 Host 注入 `ORDERS_MCP_SERVICE_TOKEN`、`ORDERS_MCP_DB_PATH` 和已认证的 `actor_id`。这不是生产支付或订单系统。
