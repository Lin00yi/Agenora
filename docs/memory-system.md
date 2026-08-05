# KnowFlow Memory 记忆系统

> 本文说明当前项目已实现的会话记忆、长期记忆、上下文注入与静默写入机制。

## 1. 目标与边界

Memory 的目标不是保存全部聊天记录，而是在不让上下文无限增长的前提下，保留对后续回答有持续价值的信息。

当前系统遵循以下原则：

- 聊天完整记录仍保存在 `messages` 表，作为可追溯的事实来源；
- 最近会话保留原文，较早会话压缩为摘要；
- 长期记忆只保存明确或高置信度的稳定偏好、约束和事实；
- 自动记忆在后台静默完成，不要求用户在聊天时确认；
- 用户仍可通过 API / 记忆管理页查看、编辑或删除已保存的长期记忆；
- 密钥、密码、证件号、银行卡样式数字等敏感内容不得写入长期记忆。

## 2. 三层记忆模型

| 层级 | 实现 | 生命周期 | 进入模型的形式 |
|---|---|---|---|
| 短期记忆 | 最近对话消息 | 当前会话 | 原文消息 |
| 中期记忆 | `ConversationSummary` | 单个会话 | 滚动摘要 |
| 长期记忆 | `UserMemory` / `user_memories` | 跨会话、按用户隔离 | Profile 稳定偏好 + 与当前问题相关的检索块 |

### 2.1 短期记忆

短期记忆是当前会话最近的原始 `user` / `assistant` 消息。系统默认保留最近 10 轮，即最多 20 条消息；当实际 token 预算不够时，优先保留最新消息并从最早消息开始裁剪。

短期记忆用于处理“继续刚才的方案”“按上一步改”等强依赖当前对话上下文的请求。

### 2.2 中期记忆：滚动摘要

当完整会话历史达到历史预算的 72% 时，系统将早于最近 10 轮的消息整理为 `ConversationSummary`：

```text
早期完整消息
  → 抽取式会话摘要
  + 最近 10 轮完整消息
```

当前摘要优先使用独立、无工具的 LLM 调用增量维护六段式结构化摘要；未配置可用模型或调用失败时，才回退到确定性抽取摘要。两种路径都会受摘要 token 预算限制，且摘要内容仅作为数据，不能覆盖系统规则。

达到 85%（`force_summarize`）时，即使较早消息较少（≥2 条）也会尝试写入摘要，避免 UI「即将压缩」状态只改标签不落库。

随着会话继续，原本的“最近消息”会逐步变旧，并在后续压缩时纳入新的摘要覆盖范围，因此称为滚动摘要。

### 2.3 长期记忆：`UserMemory`

长期记忆与聊天记录、会话摘要分开存储，按 `user_id` 隔离，可跨会话检索。它适合保存：

- 稳定偏好：默认语言、回复风格、长度要求；
- 长期约束：项目或团队的技术规范；
- 用户显式要求记住的信息；
- 与当前知识库绑定的项目规则。

注入时拆成两路，避免同一条记忆双写：

| 块 | 内容 | 何时注入 |
|---|---|---|
| **Profile** | 仅 `response_language` / `response_style` / `response_max_chars` | 每轮必带（有则注入） |
| **Memory 检索块** | 与当前问题相关的约束 / 事实 / 其他偏好；排除已进 Profile 的行 | 按查询混合检索，最多 4 条 |

## 3. 静默写入流程

用户消息写入会话时，后端同步执行长期记忆候选提取：

```text
POST /api/conversations/{conversation_id}/messages
  ↓
保存 Message
  ↓
extract_memory_candidates(content)
  ↓
敏感信息与问句过滤
  ↓
生成结构化 MemoryCandidate
  ↓
同键记忆去重 / 覆盖
  ↓
生成向量（尽力而为）+ 记忆整合
  ↓
保存 UserMemory
```

写入对用户无感：不会在聊天窗口弹出“是否保存”确认框。

### 3.1 显式写入

下列句式会作为高置信度显式记忆保存：

```text
记住：我偏好中文回答
请记住：项目后端使用 FastAPI
以后记住：报告控制在 500 字内
请把这个记到长期记忆：客户属于教育行业
```

对应正则位于 `extract_explicit_memory_candidate()`。

### 3.2 隐式高置信度写入

系统也会静默识别明确表达“未来默认规则”的信息，例如：

```text
以后请用中文并且简洁回复。
以后技术报告不超过 500 字。
项目必须统一使用 FastAPI。
```

当前规则只覆盖高精度场景：

| 候选类型 | 结构化键 | 示例 |
|---|---|---|
| `preference` | `response_language` | 以后请用中文回复 |
| `preference` | `response_style` | 默认简洁回答 |
| `preference` | `response_max_chars` | 以后回复不超过 500 字 |
| `constraint` | `constraint.<topic>`（如 `constraint.stack.database`） | 项目必须统一使用 FastAPI / PostgreSQL |

已知主题包括：`stack.database`、`stack.backend`、`stack.frontend`、`stack.language`、`stack.orm`、`stack.vector`、`policy.testing`、`policy.ci`、`policy.security`。无法归类时回退到 `constraint.misc:<hash>`，避免无关约束互相覆盖。

同一 `(user, scope, scope_id, type, memory_key)` 下新值会 supersede 旧值；写入与整合还会按主题合并遗留的哈希键约束（例如旧的 `constraint:<hash>` 与新的 `constraint.stack.database`）。

问句不会触发隐式记忆，例如“这次可以用中文吗？”不会被保存。

显式「记住：项目必须…」若能推断主题，会提升为 `constraint` 而非自由 `explicit`，以便参与主题冲突消解。

### 3.3 低频 LLM 补召回

会话结束或闲置时，系统会再跑一遍整段对话的记忆抽取：

- 前端切换 / 新建会话时调用 `POST /api/conversations/{id}/finalize`
- 后台 `memory_maintenance` 对闲置会话做同样处理（默认约 24h）

该路径在规则扫描之外，额外调用无工具 LLM（`source=auto_session`，置信度阈值约 0.72）补召回稳定偏好、约束和事实。实时聊天路径仍保持规则高精度，避免每条消息都烧抽取成本。

## 4. 数据模型

`UserMemory` 当前包含以下关键字段：

| 字段 | 作用 |
|---|---|
| `user_id` | 用户隔离 |
| `scope` / `scope_id` | `personal` 或 `kb` 作用域；KB 规则只在对应知识库生效 |
| `type` | `explicit`、`preference`、`constraint`、`fact` 等类别 |
| `memory_key` / `memory_value` | 机器可比较的结构化键值 |
| `content` | 供模型理解的自然语言描述 |
| `source` | `explicit`、`auto_rule`、`auto_session`、`user_edited` |
| `confidence` / `importance` | 检索排序信号 |
| `status` | `active`、`superseded`、`deleted`、`expired` |
| `supersedes_memory_id` | 新记忆覆盖旧记忆时的关联 |
| `source_message_ids` | 来源消息，用于可追溯性 |
| `embedding_json` / `embedding_fingerprint` | 记忆向量及其模型空间标识，用于语义检索 |

数据库启动时会通过 additive migration 为既有 `user_memories` 表追加这些字段；旧的显式记忆仍然可读取。

## 5. 去重、覆盖与冲突处理

对同一用户，系统按以下组合定位可覆盖的记忆：

```text
user_id + scope + scope_id + type + memory_key
```

例如：

```text
旧：response_language = zh-CN
新：response_language = en
```

写入新值时：

1. 旧记忆状态改为 `superseded`；
2. 创建新的 `active` 记忆；
3. 新记忆的 `supersedes_memory_id` 指向旧记忆；
4. 后续检索只使用 `active` 记忆。

如果键和值都相同，则不重复创建记录，只更新来源消息、置信度、重要性和更新时间。

## 6. 混合检索、整合与上下文注入

一次聊天请求构建上下文时，系统会：

```text
当前用户问题
  ↓
构建 Profile（稳定 response_* 偏好）
  ↓
按 user_id 查询 active UserMemory（排除已进 Profile 的行与 response_* 键）
  ↓
过滤不匹配的 KB 作用域
  ↓
关键词相关性 + 向量余弦相似度 + 类型匹配 + 作用域 + 阻尼后的重要性/置信度排序
  ↓
近重复折叠（同 type/scope、余弦 ≥ 0.88 只留更高分）
  ↓
取最多 4 条 Memory
  ↓
与 Profile、会话摘要、最近消息组装
```

入选门槛：关键词命中，或语义余弦 ≥ `0.55`。重要度 / 置信度仅以 `0.25` 系数参与排序，不能单独把弱相关高重要度记忆抬进上下文。偏好类问题（如“我的默认语言是什么”）会给非 Profile 的 `preference` 类型额外加分，但仍须先过关键词或语义门；当前 KB 范围内的记忆也会获得作用域加分。稳定回复偏好改由 Profile 每轮注入，不再占用检索名额。

向量与 `UserMemory` 同行保存，适用于当前每个用户较小的记忆集合，不额外创建一套按用户拆分的向量库。向量的 `embedding_fingerprint` 必须与查询向量一致才会参与余弦计算；模型切换后的旧向量会在后续检索时渐进回填。Embedding 未配置、上游异常或回填失败时，系统自动退回关键词检索，聊天不会失败。

每次新增或编辑 Memory 后，整合器会以幂等方式：

1. 将已到期的自动 Memory 标为 `expired`；
2. 修复同一结构化键下并存的 active 值，保留最新值并将旧值标为 `superseded`；
3. 对同类型、同作用域、同向量空间且余弦相似度至少为 `0.88` 的显式/约束记忆合并来源与排序信号。

高阈值只用于去除近乎重复的记录；语义相关但不等价的事实不会被自动删除。

此外可由单个外部 Cron/Worker 定时执行完整维护，覆盖不再产生新消息的用户：

```bash
cd backend
python -m src.infra.memory_maintenance
```

该命令会按用户提交处理结果，并输出 `users_scanned`、过期、覆盖、去重、向量回填及失败数量。部署时只应调度一个实例；管理员也可以调用 `POST /api/admin/memory-maintenance` 进行有界的手动执行。

最终的上下文顺序为：

```text
业务模式 System Prompt
  + Profile（稳定偏好）
  + 长期记忆检索块
  + 滚动会话摘要
  + 最近消息
  + 当前用户问题
  + Agent 工具/RAG 结果
```

长期记忆和摘要会被合并到唯一的 Provider 安全系统提示词中：

- OpenAI-compatible Provider 使用唯一 `system` message；
- Anthropic Provider 使用顶层 `system` 参数；
- 记忆和摘要不会以 `system` 角色残留在普通对话消息序列中。

聊天完成后 SSE `done` 事件会带回 `memory_trace`（Profile / 检索记忆 / 摘要元数据），前端可按消息展示注入 Trace。

## 7. 上下文预算

系统会预留输出、System Prompt/Tool Schema 和安全余量，再为历史消息分配预算。**仅当会话绑定 KB 时**才额外预留 RAG（8,000 token）；普通聊天不再扣减该预留。

同时限制：

- Profile 块：最多 700 token；
- 长期记忆检索块：最多 1,200 token；
- 会话摘要：最多 2,600 token；
- RAG 检索结果：最多 8,000 token（仅 KB 模式）；
- 最近消息：使用剩余实际 token 预算，优先保留最新内容。

模型调用前还会重新测量最终 System Prompt、Tool Schema 和消息内容，避免固定预留与真实内容大小不一致。

Token 计量使用 **tiktoken**（按模型族选择 `o200k_base` / `cl100k_base`；DeepSeek/Claude/BYOK 以 `cl100k_base` 为预算代理），并加约 3% 余量吸收跨 tokenizer 偏差。tiktoken 不可用时回退到 CJK 启发式估计。构建上下文与 `allocate_provider_context` 会通过 `token_model_scope` 绑定当前模型。

上下文状态 API 的占用率（`percent` / `current_tokens`）使用**摘要压缩后的有效上下文**（摘要 token + 最近轮次），而不是原始全量历史；原始体积仍可通过 `raw_history_tokens` 查看。

## 8. 管理 API 与前端

静默写入不代表不可控。当前已有以下接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/conversations/memories` | 查看当前用户的 Memory（可按 status 过滤） |
| `GET` | `/api/conversations/memories/export` | 导出 Memory 为 JSON（默认全部状态） |
| `PATCH` | `/api/conversations/memories/{memory_id}` | 编辑内容、重要性、状态或过期时间（`expires_at`，传 `null` 表示长期有效） |
| `DELETE` | `/api/conversations/memories/{memory_id}` | 逻辑删除记忆 |
| `POST` | `/api/conversations/{id}/finalize` | 会话结束时的 LLM 记忆补召回 |
| `GET` | `/api/conversations/{id}/context-status` | 上下文占用与压缩状态 |

前端：

- `/memories` 记忆管理页：查看、编辑内容与过期时间、改重要性、删除、按当前筛选导出
- 设置页也可浏览记忆列表
- 聊天消息可展示 Memory 注入 Trace（`memory_trace`）

## 9. 安全与隐私

- 只处理用户消息，不从模型回复自动提取长期记忆；
- 显式与隐式写入都会经过敏感模式检查；
- 用户、KB 作用域隔离；
- 保存的 Memory 在系统提示词中被标记为“仅供参考的数据”，不能覆盖安全规则或工具权限；
- 用户可删除已保存的记忆。

## 10. 当前限制与后续方向

当前实现仍存在以下限制：

- 实时路径仍以规则为主；LLM 抽取仅在 finalize / idle 维护时运行；
- 向量以 JSON 存在关系库中，适合小规模个人记忆；达到较大规模后应迁移至支持 metadata filter 的专用向量索引；
- 过期与整合可由独立 Worker/Cron 覆盖长期不活跃用户；部署平台仍需负责单实例调度与重试；
- 约束主题词表覆盖常见技术栈与策略；词表外约束仍用 `constraint.misc:<hash>`，需要时可扩展 `CONSTRAINT_TOPICS`；
- DeepSeek/Claude 无官方公开 tokenizer 时仍用 tiktoken 代理，极端文本上可能与供应商计数有偏差。

下一阶段建议优先引入：离线评测小集。

## 11. 关键代码位置

| 模块 | 文件 |
|---|---|
| 记忆候选、检索、会话摘要、上下文预算 | `backend/src/conversations/context.py` |
| Memory 数据模型 | `backend/src/conversations/models.py` |
| 消息写入与 Memory 管理接口 | `backend/src/conversations/routes.py` |
| 定时维护（闲置 finalize / 整合 / 向量回填） | `backend/src/infra/memory_maintenance.py` |
| 既有数据库的增量迁移 | `backend/src/infra/database.py` |
| 对话请求中构建上下文 | `backend/src/app.py` |
| Provider 安全系统提示词组装 | `backend/src/agent/nodes.py` |
| 前端 API 类型与调用封装 | `frontend/lib/conversations-api.ts` |
| 记忆管理页 | `frontend/app/memories/page.tsx` |
| 设计评审（修复依据） | `context-memory-review.md` |
