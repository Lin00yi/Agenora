# Mock Orders MCP

用于本地开发和自动化测试的 stdio MCP 服务。它拥有自己的模拟订单 SQLite 数据，不属于 `backend` 业务代码。

由 Agenora Host 通过 `backend/src/harness/mcp/orders.py` 按工具调用启动。Host 使用本项目的 `uv.lock` 创建/复用独立环境，不会把 `backend` 的源码路径注入给服务：

```bash
uv run --directory mock-mcp/orders python -m mock_orders_mcp.server
```

运行时需要由 Host 注入 `ORDERS_MCP_SERVICE_TOKEN`、`ORDERS_MCP_DB_PATH` 和已认证的 `actor_id`。这不是生产支付或订单系统。

## 演示数据与工具

首次访问某个用户时，服务会写入 20 笔彼此独立的订单样本。它覆盖待发货、运输中、已完成、部分退款、已退款、已关闭，以及售后期内/已过期、全额/部分退款、等待确认/确认过期/已完成退款等规则。订单返回商品名称、商品 URL 和图片 URL、SKU/规格、金额拆分、支付方式（脱敏）、物流/收货信息（脱敏）、发票、售后资格和历史退款。

可用 MCP 工具：

- `list_orders` / `get_order`：查询订单与商品明细。
- `list_refunds` / `get_refund`：查询退款记录、退款状态与时间线。
- `prepare_refund` / `confirm_refund`：退款仍是两阶段写操作；确认前绝不执行。相同订单、原因和金额的有效确认单会复用，以支持工作流重放时的幂等性。

## 已覆盖的 mock 规则

- 用户归属：所有读取和写入均按 Host 注入的 `actor_id` 过滤，跨用户订单不可见。
- 订单状态：`paid`、`shipped`、`completed`、`partial_refunded`、`refunded`、`closed`。
- 售后资格：订单状态、已退款金额和售后截止时间共同决定可退款金额；全额退款、关闭和过期订单不可再创建退款。
- 金额校验：退款金额必须大于零且不超过当前可退金额，可发起全额或部分退款。
- 退款状态：`awaiting_confirmation`、`completed`、`expired`，均有可查询时间线。
- 高风险确认：仅精确确认语可执行；错误确认、过期确认和重复确认不会重复退款。
- 可重放：相同订单、原因和金额在确认单有效期内复用同一确认单。
