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

`backend/.env` 中须配置可用的 LLM；知识库检索还须配置 Embedding。没有 Key 时前后端仍可启动并访问界面，但无法完成实际模型对话。本地示例未配置 `LIGHTRAG_BASE_URL`，因此不会启用图谱检索；需要该能力时请改为 Docker 模式，或自行启动 LightRAG 与 Neo4j 后配置该地址。

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
| `./scripts/backup.sh [目录]` | 备份 Docker 的 PostgreSQL 与后端数据卷。 |

Schema 演进可用 Alembic（`backend/alembic`）；现有库可 `alembic stamp head`。

## 文档

更细的架构、部署与记忆系统说明见 [`docs/`](docs/)。

## 协议

MIT · 个人维护 · [GitHub](https://github.com/Lin00yi/Agenora)
