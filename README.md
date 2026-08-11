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

本地开发安装 Postgres 驱动：`pip install -e '.[postgres]'`（Docker 镜像已含）。
Schema 演进可用 Alembic（`backend/alembic`）；现有库可 `alembic stamp head`。

## 快速开始

### Docker（推荐）

```bash
cp env.docker.example .env
# 编辑 .env：POSTGRES_PASSWORD / JWT_SECRET / PUBLIC_URL
./scripts/deploy.sh
```

浏览器打开 `http://localhost`。

### 本地开发

```bash
# 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e '.[milvus]'
cp env.example .env   # 填入必要配置
python -m uvicorn src.app:app --host 0.0.0.0 --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev           # http://localhost:3000
```

## 文档

更细的架构、部署与记忆系统说明见 [`docs/`](docs/)。

## 协议

MIT · 个人维护 · [GitHub](https://github.com/Lin00yi/Agenora)
