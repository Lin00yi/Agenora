# Agenora

个人项目：私有 RAG 知识库 + 透明 Agent。

上传文档 / 抓取网页 → 选中知识库 → 用自然语言提问。答案带原文引用，检索与工具调用过程可见。

## 能做什么

- **私有知识库** — PDF / Markdown / Word / 网页，按账号隔离
- **混合检索** — 关键词 + 向量，可选 cross-encoder 重排
- **透明 Agent** — 思考链展示工具调用、耗时与命中来源
- **BYOK** — 自带 LLM / Embedding Key，数据留在你的部署环境
- **协作** — 知识库成员可通过邮箱邀请加入

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16 · React 18 · Tailwind |
| 后端 | FastAPI · LangGraph · SQLAlchemy |
| 存储 | SQLite / PostgreSQL · Milvus Lite（可换 Qdrant）· 可选 LightRAG/Neo4j |

## 启动方式

### 方式一：本地开发（推荐开发时使用）

依赖：Python 3.11、Node.js 20+。本模式使用 SQLite 与 Milvus Lite；不需要 Docker、PostgreSQL、Neo4j 或 LightRAG。

首次安装与配置：

```bash
# 后端
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[milvus]'
cp .env.example .env

# 前端
cd ../frontend
npm ci
cp .env.example .env
```

然后在项目根目录同时启动两个服务：

```bash
./scripts/dev.sh
```

- 前端：<http://localhost:3000>
- 后端健康检查：<http://localhost:8000/health>
- 停止：在运行脚本的终端按 `Ctrl+C`。

模型上下文、实验室名称和 Logo 由 [`@opencode-ai/models`](https://models.dev/) 的离线快照提供；升级该依赖后执行以下命令，并提交生成的 `backend/config/models.dev.snapshot.json`：

```bash
cd frontend
npm run sync:model-catalog
```

`backend/.env` 中须配置可用的 LLM；知识库检索还须配置 Embedding。没有 Key 时前后端仍可启动并访问界面，但无法完成实际模型对话。本地示例未配置 `LIGHTRAG_BASE_URL`，因此不会启用图谱检索；需要该能力时请改为 Docker 模式，或自行启动 LightRAG 与 Neo4j 后配置该地址。

### 聊天中的知识库入口

`NEXT_PUBLIC_CHAT_KB_SELECTION_MODE` 控制输入框是否展示知识库下拉框，默认值为 `hidden`：新建会话不展示“通用对话”或知识库控件。服务端会先在当前用户有读取权限、且已有向量数据的知识库中进行意图路由；只有判断问题需要内部资料且能高/中置信度选出一个 KB 时，才会自动检索并将会话绑定到该 KB。闲聊、创作、翻译、低置信度或路由失败会保留为通用聊天。

用户也可从知识库详情页点击「基于此知识库提问」，创建一个显式绑定该知识库的会话。只有需要让用户自行选择知识库时，才将该变量设为 `selectable`。一旦自动或显式绑定，后续请求始终沿用已保存的 `kb_id`，避免同一会话逐轮跳库。

后端通过 `KB_AUTO_ROUTE_MODE=llm_fallback` 启用规则优先、轻量 LLM 兜底的自动路由；可改为 `off`、`rule_only` 或 `always_llm`。接口层只准备已授权且可检索的候选集；Planner 为未绑定会话生成 `kb_route` DAG 节点，Supervisor 委托 `kb_router` 后再动态展开为 RAG 或通用聊天任务。`KB_AUTO_ROUTE_MAX_CANDIDATES` 默认为 8，用于限制单轮交给路由器的已授权候选数。Docker 部署修改根目录 `.env` 后需重启后端；若同时修改前端选择器策略，使用 `docker compose up -d --build frontend` 重建前端。

文档上传会先创建可恢复的入库任务，再由进程内任务立即尝试处理。Docker 模式会自动运行 `ingestion-worker`；本地开发若需要从重启前恢复未完成的入库，可另开终端执行：

```bash
cd backend
.venv/bin/python -m src.capabilities.knowledge.application.jobs
```

### RAG 评测与监控闭环

离线评测使用版本化 JSONL 黄金集，检索相关性以稳定的 `document_id` 计算 Recall@K、Precision@K、MRR、nDCG；带有回答引用的回放结果还会计算引用精确率与覆盖率。先复制示例文件并将占位符替换为目标知识库中真实文档 ID，黄金集和基线应随知识库内容一起评审、提交。

```bash
cd backend
cp config/rag_eval_cases.example.jsonl config/rag_eval_cases.jsonl
# 回放已有结果，并以显式阈值作为 CI / 发布门禁
.venv/bin/python -m src.harness.evaluation.cli \
  --dataset config/rag_eval_cases.jsonl \
  --results config/rag_eval_results.example.jsonl \
  --k 3 --min-recall-at-k 0.80 --min-mrr 0.70 --min-ndcg-at-k 0.70

# 对真实索引执行检索并产出可审查的结果快照
.venv/bin/python -m src.harness.evaluation.cli \
  --dataset config/rag_eval_cases.jsonl --kb-id <kb-id> \
  --write-results artifacts/rag-retrieval.jsonl --report artifacts/rag-report.json
```

若本地正在运行使用 Milvus Lite 的后端，不能另起进程直接打开同一个向量文件；管理员可让 CLI 复用运行中的服务（`api-token` 不要提交到仓库）：

```bash
.venv/bin/python -m src.harness.evaluation.cli \
  --dataset config/rag_eval_cases.jsonl --kb-id <kb-id> \
  --api-base-url http://127.0.0.1:8000 --api-token <admin-bearer-token> \
  --write-results artifacts/rag-retrieval.jsonl --report artifacts/rag-report.json
```

每个生产知识库应将实际运行的基线和允许回退阈值保存为可审查的 JSON；Roogoo 见 `backend/config/rag_eval_roogoo_gate.json`。检索按 **文档 ID 去重** 后计算 Recall@K / MRR / nDCG；每条用例默认只标 canonical 一篇文档（与 `source_url` / `expected_citation_document_ids` 一致），不要把相关文章塞进召回分母。只有真正需要多篇才能答全的问题，才标多个 `expected_document_ids`。CLI 可直接读门禁：

```bash
.venv/bin/python -m src.harness.evaluation.cli \
  --gate config/rag_eval_roogoo_gate.json \
  --api-base-url http://127.0.0.1:8000 --api-token <admin-bearer-token> \
  --write-results artifacts/rag-retrieval.jsonl --report artifacts/rag-report.json
```

知识库详情页的「测评」分区把同一套能力交给 owner / editor：可为每个 KB 上传黄金集 JSONL 与门禁、对当前索引跑检索回归、回放已保存或上传的 `retrieval.jsonl`，并查看该 KB 的线上检索健康。回归产物写在 `backend/data/eval_runs/`（已由 `data/` gitignore 排除）。

上线后，`search_kb` / `search_kg` 的结果数、最高相关度、延迟和失败状态会写入 Trace。Docker 自动运行 `rag-monitor`，按 `RAG_MONITOR_*` 阈值输出结构化告警日志；管理员可在 `/admin/rag` 查看过去 24 小时的空检索率、错误率、P95 延迟和相关度。没有 Docker 时可手动运行一次（加 `--fail-on-alert` 会在告警时以退出码 2 结束，适合 cron/CI）：

```bash
cd backend
.venv/bin/python -m src.bootstrap.workers.rag_monitor --once --fail-on-alert
```

### 方式二：Docker 本地调试（基础 RAG）

需要 Docker Desktop / Docker Compose。根目录 `.env` 由 Compose 读取，和 `backend/.env`、`frontend/.env` 的本地开发配置相互独立。

```bash
cp env.docker.example .env
# 填写 POSTGRES_PASSWORD、JWT_SECRET、NEO4J_PASSWORD、LIGHTRAG_API_KEY、PUBLIC_URL，
# 以及需要的模型/Embedding Key（后两个 KG 密钥只在启用 kg profile 时使用）
./scripts/deploy.sh
```

此模式自动合并 `docker-compose.override.yml`，启动 PostgreSQL、API、持久化入库
worker、RAG 监控与前端；首次启动时 `migrate` 一次性执行 Alembic。默认不启动
Neo4j/LightRAG：普通向量 RAG 不依赖图谱服务。

- 前端：<http://localhost:3000>
- 后端：<http://localhost:8000/health>

若某个部署需要图谱检索，在填写 `NEO4J_PASSWORD` 和 `LIGHTRAG_API_KEY` 后显式启用
`kg` profile：

```bash
docker compose --profile kg up -d --build
```

这会额外启动 Neo4j 与 LightRAG。同步设置 `LIGHTRAG_ENABLED=true`、
`LIGHTRAG_BASE_URL=http://lightrag:9621`，并在需要图谱的知识库上开启 KG。
本地 override 启用时，Neo4j Browser 位于 <http://localhost:7474>，LightRAG 位于
<http://localhost:9621>。

### 方式三：HTTPS 生产部署

生产环境只暴露 Nginx 的 `80/443`，不加载本地 override：

```bash
cp env.docker.example .env
# 填写真实 DOMAIN、PUBLIC_URL=https://<你的域名>、所需密钥与模型配置
docker compose -f docker-compose.yml --profile production up -d --build
```

Nginx 配置会读取 `/etc/letsencrypt/live/$DOMAIN/` 下已有的证书；首次生产部署前需自行完成证书签发。部署后检查：

```bash
docker compose -f docker-compose.yml --profile production ps
curl -fsS https://<你的域名>/health
```

### 常用脚本

| 命令 | 用途 |
|---|---|
| `./scripts/dev.sh` | 本地同时启动 FastAPI 与 Next.js，适合日常开发。 |
| `./scripts/deploy.sh` | 构建并以 Docker Compose 启动本地调试编排；可传 `backend` 仅重建后端。 |
| `./scripts/logs.sh [backend\\|frontend\\|all]` | 跟踪 Docker Compose 服务日志，默认后端。 |
| `AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME=1 ./scripts/backup.sh [目录]` | 创建 PostgreSQL 逻辑备份、后端/LightRAG 数据归档与 Neo4j 离线 dump。 |
| `AGENORA_RESTORE_CONFIRM=RESTORE_AGENORA ./scripts/restore.sh <备份目录>` | 校验并恢复完整备份；会覆盖所有持久数据。 |

Schema 演进只由 Alembic 管理。Compose 的 `migrate` 一次性服务会在 backend / worker
启动前执行 `alembic upgrade head`；应用进程不会在生产环境创建、修改或删除表。

从旧版“应用启动自动建表”部署升级前，请先备份并在维护窗口核对 schema。若现有库已经
与旧版模型一致，可执行 `alembic stamp 0003_kb_eval`，再执行 `alembic upgrade head`，将其
纳入受管版本；不要对未核对的数据库直接 stamp。

### 备份与恢复

`backup.sh` 的 PostgreSQL 备份使用 `pg_dump`，而不是直接打包运行中的数据卷。Neo4j Community 只支持离线 dump，因此脚本要求明确设置 `AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME=1`，并在图数据库短暂停机期间备份 `system` 与 `neo4j` 两个数据库。每个备份目录都有 SHA-256 清单。

恢复会停止整个 Compose 栈、校验清单并覆盖 PostgreSQL、Neo4j、backend、LightRAG 的全部持久数据；先在隔离环境演练，且只在确实需要恢复时执行。Neo4j Community 的离线 dump/load 限制见 [官方运维文档](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/)。

## 文档

更细的架构、部署与记忆系统说明见 [`docs/`](docs/)。

## 协议

MIT · 个人维护 · [GitHub](https://github.com/Lin00yi/Agenora)
