# Agenora

个人项目：私有 RAG 知识库 + 透明 Agent。

上传文档 / 抓取网页 → 选中知识库 → 用自然语言提问。答案带原文引用，检索与工具调用过程可见。

## 能做什么

- **私有知识库** — PDF / Markdown / Word / 网页，按账号隔离
- **混合检索** — 关键词 + 向量，可选 cross-encoder 重排
- **透明 Agent** — 思考链展示工具调用、耗时与命中来源
- **BYOK** — 自带 LLM / Embedding Key，数据留在你的部署环境
- **协作分享** — 知识库成员邀请与匿名分享链接（可选）

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14 · React 18 · Tailwind |
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

文档上传会先创建可恢复的入库任务，再由进程内任务立即尝试处理。Docker 模式会自动运行 `ingestion-worker`；本地开发若需要从重启前恢复未完成的入库，可另开终端执行：

```bash
cd backend
.venv/bin/python -m src.infra.ingestion_jobs
```

### RAG 评测与监控闭环

离线评测使用版本化 JSONL 黄金集，检索相关性以稳定的 `document_id` 计算 Recall@K、Precision@K、MRR、nDCG；带有回答引用的回放结果还会计算引用精确率与覆盖率。先复制示例文件并将占位符替换为目标知识库中真实文档 ID，黄金集和基线应随知识库内容一起评审、提交。

```bash
cd backend
cp config/rag_eval_cases.example.jsonl config/rag_eval_cases.jsonl
# 回放已有结果，并以显式阈值作为 CI / 发布门禁
.venv/bin/python -m src.rag_eval.cli \
  --dataset config/rag_eval_cases.jsonl \
  --results config/rag_eval_results.example.jsonl \
  --k 3 --min-recall-at-k 0.80 --min-mrr 0.70 --min-ndcg-at-k 0.70

# 对真实索引执行检索并产出可审查的结果快照
.venv/bin/python -m src.rag_eval.cli \
  --dataset config/rag_eval_cases.jsonl --kb-id <kb-id> \
  --write-results artifacts/rag-retrieval.jsonl --report artifacts/rag-report.json
```

若本地正在运行使用 Milvus Lite 的后端，不能另起进程直接打开同一个向量文件；管理员可让 CLI 复用运行中的服务（`api-token` 不要提交到仓库）：

```bash
.venv/bin/python -m src.rag_eval.cli \
  --dataset config/rag_eval_cases.jsonl --kb-id <kb-id> \
  --api-base-url http://127.0.0.1:8000 --api-token <admin-bearer-token> \
  --write-results artifacts/rag-retrieval.jsonl --report artifacts/rag-report.json
```

每个生产知识库应将实际运行的基线和允许回退阈值保存为可审查的 JSON；Roogoo 的首版示例见 `backend/config/rag_eval_roogoo_gate.json`。例如其发布门禁为 `Recall@3 ≥ 0.95`、`MRR ≥ 0.85`、`nDCG@3 ≥ 0.88`。

上线后，`search_kb` / `search_kg` 的结果数、最高相关度、延迟和失败状态会写入 Trace。Docker 自动运行 `rag-monitor`，按 `RAG_MONITOR_*` 阈值输出结构化告警日志；管理员可在 `/admin/rag` 查看过去 24 小时的空检索率、错误率、P95 延迟和相关度。没有 Docker 时可手动运行一次（加 `--fail-on-alert` 会在告警时以退出码 2 结束，适合 cron/CI）：

```bash
cd backend
.venv/bin/python -m src.observability.rag_monitor --once --fail-on-alert
```

### 方式二：Docker 本地调试（完整依赖）

需要 Docker Desktop / Docker Compose。根目录 `.env` 由 Compose 读取，和 `backend/.env`、`frontend/.env` 的本地开发配置相互独立。

```bash
cp env.docker.example .env
# 填写 POSTGRES_PASSWORD、JWT_SECRET、PUBLIC_URL，以及需要的模型/Embedding Key
./scripts/deploy.sh
```

此模式自动合并 `docker-compose.override.yml`：

- 前端：<http://localhost:3000>
- 后端：<http://localhost:8000/health>
- Neo4j Browser：<http://localhost:7474>
- LightRAG：<http://localhost:9621>

### 方式三：HTTPS 生产部署

生产环境只暴露 Nginx 的 `80/443`，不加载本地 override：

```bash
cp env.docker.example .env
# 填写真实 DOMAIN、PUBLIC_URL=https://<你的域名>、密钥与模型配置
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

Schema 演进可用 Alembic（`backend/alembic`）；现有库可 `alembic stamp head`。

容器升级前，在只运行一个维护副本时执行 `docker compose run --rm backend alembic upgrade head`；应用启动的兼容性建表仍会保护旧版个人部署，但生产变更以 Alembic 版本为准。

### 备份与恢复

`backup.sh` 的 PostgreSQL 备份使用 `pg_dump`，而不是直接打包运行中的数据卷。Neo4j Community 只支持离线 dump，因此脚本要求明确设置 `AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME=1`，并在图数据库短暂停机期间备份 `system` 与 `neo4j` 两个数据库。每个备份目录都有 SHA-256 清单。

恢复会停止整个 Compose 栈、校验清单并覆盖 PostgreSQL、Neo4j、backend、LightRAG 的全部持久数据；先在隔离环境演练，且只在确实需要恢复时执行。Neo4j Community 的离线 dump/load 限制见 [官方运维文档](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/)。

## 文档

更细的架构、部署与记忆系统说明见 [`docs/`](docs/)。

## 协议

MIT · 个人维护 · [GitHub](https://github.com/Lin00yi/Agenora)
