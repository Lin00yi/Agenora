# 上下文与记忆系统设计评审

> 来源：Cursor canvas `context-memory-review` · 2026-08-05  
> 代码锚点：`backend/src/conversations/context.py` · `backend/src/agent/nodes.py` · `docs/memory-system.md`

## 总评

**方向合理，注入层有冗余。** KnowFlow 的三层记忆栈（短期消息 → 滚动摘要 → 跨会话 `UserMemory`）+ KB RAG 正交通道本身没有问题；精度优先、静默写入、Provider 安全合并也做对了。真正需要收敛的是「Profile + 检索记忆」双通道重叠、预算预留过保守、以及文档落后于实现——不是推倒重来。

| 维度 | 判定 |
|---|---|
| 三层记忆模型 | 合理 |
| Profile 重叠风险 | 中 |
| 预算 / 计量偏差 | 中 |
| 架构推倒风险 | 低 |

## 当前装配流水线

一次 `/api/chat`（带 `conversation_id`）时的真实顺序：

1. **消息入库** — user 消息 → 规则静默写 `UserMemory`（显式 / 高置信隐式）
2. **`build_context_for_conversation`** — 算预算 → 摘要（≥72%）→ 检索记忆 top6 → 构建 Profile → 裁剪最近轮次
3. **注入块（system 标签）** — profile → memory → summary → recent user/assistant
4. **`reason_node` 合并** — 模式 prompt + `<conversation_context>` + 可选 injection guard + 可选 `<kb_context>`
5. **`allocate_provider_context`** — 实测 system/tools，再裁对话历史；SSE 带回 `memory_trace`

## Token 预算构成（默认 16k 未知模型）

固定预留：output 4096 + system/tools 6000 + RAG 8000 + safety 2000。  
历史可用约 `max(4000, window − 20096)`——在 16k 窗口上几乎被压到下限。

注入块上限：Profile ≤700 · Memory ≤1200 · Summary ≤2600 · 最近消息用剩余。

## 问题清单

| 严重度 | 问题 | 影响 | 位置 |
|---|---|---|---|
| 高（体验/浪费） | Profile 与检索 Memory 双注入 | 同一偏好可能出现两次，挤占预算并放大单一事实权重 | `build_context` + profile/memory_block |
| 中（预算） | 非 KB 模式仍扣 `RAG_RESERVE=8k` | 普通聊天历史窗口被无谓压缩 | `compute_budget()` |
| 中（计量） | UI percent 用原始全量历史 | 摘要后仍显示「很满」；`force_summarize` 只改 UI 不强制写摘要 | `context_status_payload` / `compute_budget` |
| 中（精度） | 启发式 token 估计 + 二次预留 | 偏高估 → 过度裁剪 | `estimate_tokens` + `allocate_provider_context` |
| 低（文档） | `memory-system.md` 滞后 | 缺 Profile 层、LLM finalize、Trace/Memories 页已存在仍写「后续」 | `docs/memory-system.md` §6/8/10 |
| 低（质量） | 中英混排 + constraint 哈希键 | Profile 英文 / Memory 中文；约束难冲突消解 | `user_profile_block` / extract rules |
| 低（边界） | 无 `conversation_id` 跳过记忆 | 旧路径 / ad-hoc 客户端无摘要与长期记忆 | `app.py` `/api/chat` |

## 分层判定

### 做得对的（保留）

- 消息表为事实源，摘要 / 记忆是派生层，可追溯
- 实时规则高精度 + finalize/idle LLM 补召回，成本和误写权衡合理
- 敏感过滤、只从 user 消息提取、context 标为数据且不可覆盖规则
- `_context_source` 白名单，防客户端 system 注入
- 同键 supersede + 高阈值语义去重；全局 `response_*` 无词重叠也注入
- RAG 与长期记忆正交，职责清晰

### 应改的

1. **Profile 是「第二次记忆」** — Profile 按 importance 抽 prefs/constraints/facts；retrieve 又按 query 抽 top6。全局偏好已在 retrieve 强制注入，Profile 再塞一遍同一批 preference——层职责不清。
2. **预算与模式脱钩** — RAG 预留应按是否走 `kb_search` 动态扣减，而不是永远 8k。
3. **计量与真实 prompt 脱节** — 压缩后 percent 仍可接近 100%；用户会以为系统没压住窗口。

## 建议收敛（修复计划）

### P0 · 注入去重 — 已完成

- Profile 只保留「每轮必带」的稳定偏好（`response_language` / `response_style` / `response_max_chars`）
- 检索块排除已进 Profile 的 `memory_id`，避免双写
- Profile 文案中文化

### P1 · 预算按模式 — 已完成

- general 模式 `RAG_RESERVE=0`；KB 模式再预留 8k
- status percent 改为「注入后有效上下文 / 可用预算」
- `force_summarize` 驱动更积极的摘要写入（降低最少 older 门槛）

### P2 · 文档与质量 — 进行中

- [x] 同步 `memory-system.md`：Profile、LLM finalize、Trace、Memories 页
- [x] 结构化约束主题键（`constraint.stack.*` / `constraint.policy.*`）
- [x] 记忆导出 / 逐条过期编辑
- [ ] 真实 tokenizer；记忆量上来再迁专用向量索引
- [ ] 离线评测小集

## 一句话结论

上下文设计不是「不合理」，而是「多了一层重叠的记忆注入 + 预算过保守」。先收敛 Profile/Memory 职责和按模式预算，比重做记忆系统更划算。约束冲突已改为主题键 supersede，不再依赖内容哈希。
