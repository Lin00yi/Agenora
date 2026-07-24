# AnyKB Memory 记忆系统

> 本文说明当前项目已实现的会话记忆、长期记忆、上下文注入与静默写入机制。

## 1. 目标与边界

Memory 的目标不是保存全部聊天记录，而是在不让上下文无限增长的前提下，保留对后续回答有持续价值的信息。

当前系统遵循以下原则：

- 聊天完整记录仍保存在 `messages` 表，作为可追溯的事实来源；
- 最近会话保留原文，较早会话压缩为摘要；
- 长期记忆只保存明确或高置信度的稳定偏好、约束和事实；
- 自动记忆在后台静默完成，不要求用户在聊天时确认；
- 用户仍可通过 API 查看、编辑或删除已保存的长期记忆；
- 密钥、密码、证件号、银行卡样式数字等敏感内容不得写入长期记忆。

## 2. 三层记忆模型

| 层级 | 实现 | 生命周期 | 进入模型的形式 |
|---|---|---|---|
| 短期记忆 | 最近对话消息 | 当前会话 | 原文消息 |
| 中期记忆 | `ConversationSummary` | 单个会话 | 滚动摘要 |
| 长期记忆 | `UserMemory` / `user_memories` | 跨会话、按用户隔离 | 与当前问题相关的记忆块 |

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

随着会话继续，原本的“最近消息”会逐步变旧，并在后续压缩时纳入新的摘要覆盖范围，因此称为滚动摘要。

### 2.3 长期记忆：`UserMemory`

长期记忆与聊天记录、会话摘要分开存储，按 `user_id` 隔离，可跨会话检索。它适合保存：

- 稳定偏好：默认语言、回复风格、长度要求；
- 长期约束：项目或团队的技术规范；
- 用户显式要求记住的信息；
- 与当前知识库绑定的项目规则。

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
| `constraint` | `constraint:<hash>` | 项目必须统一使用 FastAPI |

问句不会触发隐式记忆，例如“这次可以用中文吗？”不会被保存。

## 4. 数据模型

`UserMemory` 当前包含以下关键字段：

| 字段 | 作用 |
|---|---|
| `user_id` | 用户隔离 |
| `scope` / `scope_id` | `personal` 或 `kb` 作用域；KB 规则只在对应知识库生效 |
| `type` | `explicit`、`preference`、`constraint` 等类别 |
| `memory_key` / `memory_value` | 机器可比较的结构化键值 |
| `content` | 供模型理解的自然语言描述 |
| `source` | `explicit`、`auto_rule`、`user_edited` |
| `confidence` / `importance` | 检索排序信号 |
| `status` | `active`、`superseded`、`deleted` |
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
按 user_id 查询 active UserMemory
  ↓
过滤不匹配的 KB 作用域
  ↓
关键词相关性 + 向量余弦相似度 + 类型匹配 + 作用域 + 重要性 + 置信度排序
  ↓
取最多 6 条 Memory
  ↓
与会话摘要、最近消息组装
```

偏好类问题（如“我的默认语言是什么”）会给 `preference` 类型额外加分；当前 KB 范围内的记忆也会获得作用域加分。

向量与 `UserMemory` 同行保存，适用于当前每个用户较小的记忆集合，不额外创建一套按用户拆分的向量库。向量的 `embedding_fingerprint` 必须与查询向量一致才会参与余弦计算；模型切换后的旧向量会在后续检索时渐进回填。Embedding 未配置、上游异常或回填失败时，系统自动退回关键词检索，聊天不会失败。

每次新增或编辑 Memory 后，整合器会以幂等方式：

1. 将已到期的自动 Memory 标为 `expired`；
2. 修复同一结构化键下并存的 active 值，保留最新值并将旧值标为 `superseded`；
3. 对同类型、同作用域、同向量空间且余弦相似度至少为 `0.96` 的显式/约束记忆合并来源与排序信号。

高阈值只用于去除近乎重复的记录；语义相关但不等价的事实不会被自动删除。

最终的上下文顺序为：

```text
业务模式 System Prompt
  + 长期记忆块
  + 滚动会话摘要
  + 最近消息
  + 当前用户问题
  + Agent 工具/RAG 结果
```

长期记忆和摘要会被合并到唯一的 Provider 安全系统提示词中：

- OpenAI-compatible Provider 使用唯一 `system` message；
- Anthropic Provider 使用顶层 `system` 参数；
- 记忆和摘要不会以 `system` 角色残留在普通对话消息序列中。

## 7. 上下文预算

系统会预留输出、System Prompt/Tool Schema、RAG 和安全余量，再为历史消息分配预算。同时限制：

- 长期记忆块：最多 1,200 token；
- 会话摘要：最多 2,600 token；
- RAG 检索结果：最多 8,000 token；
- 最近消息：使用剩余实际 token 预算，优先保留最新内容。

模型调用前还会重新测量最终 System Prompt、Tool Schema 和消息内容，避免固定预留与真实内容大小不一致。

## 8. 管理 API

静默写入不代表不可控。当前已有以下接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/conversations/memories` | 查看当前用户的 active Memory |
| `PATCH` | `/api/conversations/memories/{memory_id}` | 编辑内容、重要性或状态 |
| `DELETE` | `/api/conversations/memories/{memory_id}` | 逻辑删除记忆 |

前端已提供 API 调用封装，后续可在设置页增加“我的记忆”管理视图，而不需要改变聊天中的静默体验。

## 9. 安全与隐私

- 只处理用户消息，不从模型回复自动提取长期记忆；
- 显式与隐式写入都会经过敏感模式检查；
- 用户、KB 作用域隔离；
- 保存的 Memory 在系统提示词中被标记为“仅供参考的数据”，不能覆盖安全规则或工具权限；
- 用户可删除已保存的记忆。

## 10. 当前限制与后续方向

当前实现是规则驱动的高精度 MVP，仍存在以下限制：

- 隐式识别规则覆盖面有限，尚未使用 LLM 分类或候选抽取；
- 向量以 JSON 存在关系库中，适合小规模个人记忆；达到较大规模后应迁移至支持 metadata filter 的专用向量索引；
- 过期与整合目前在新增/编辑记忆时执行；还没有定时后台任务处理长期不活跃用户；
- `constraint` 使用内容哈希键；只有高度语义重复的记录会自动合并，真正冲突的约束仍需要更强的结构化主题识别；
- Memory 管理页目前提供查看、修改重要性和删除；尚未提供导出、逐条过期时间编辑和注入 Trace；

下一阶段建议优先引入：结构化约束主题键、定时整合任务、Memory 注入 Trace 与离线评测。

## 11. 关键代码位置

| 模块 | 文件 |
|---|---|
| 记忆候选、检索、会话摘要、上下文预算 | `backend/src/conversations/context.py` |
| Memory 数据模型 | `backend/src/conversations/models.py` |
| 消息写入与 Memory 管理接口 | `backend/src/conversations/routes.py` |
| 既有数据库的增量迁移 | `backend/src/infra/database.py` |
| 对话请求中构建上下文 | `backend/src/app.py` |
| Provider 安全系统提示词组装 | `backend/src/agent/nodes.py` |
| 前端 API 类型与调用封装 | `frontend/lib/conversations-api.ts` |
