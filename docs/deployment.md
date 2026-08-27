# 部署与启动

本仓库有三套彼此独立的运行路径。不要把本地开发的 `backend/.env`、`frontend/.env` 与 Docker
使用的根目录 `.env` 混用。

| 场景 | 编排 | 数据组件 | 对外端口 |
| --- | --- | --- | --- |
| 日常开发 | `./scripts/dev.sh` | SQLite + Milvus Lite | 前端 3000、后端 8000 |
| Docker 本地验证 | `./scripts/deploy.sh` | PostgreSQL + Qdrant | 前端 3000、后端 8000 |
| HTTPS 生产部署 | `./scripts/deploy.sh --production` | PostgreSQL + Qdrant + Nginx | Nginx 80/443 |

Docker 基础编排不启动 Neo4j 和 LightRAG。图谱检索是一个额外的 `kg` profile，需显式启用。

## 1. 本地开发（无需 Docker）

前提：Python 3.11、Node.js 20+。首次执行：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[milvus]'
cp .env.example .env

cd ../frontend
npm ci
cp .env.example .env

cd ..
./scripts/dev.sh
```

访问 <http://localhost:3000>，以 <http://localhost:8000/health> 检查后端。运行脚本的终端按
`Ctrl+C` 可同时停止两个进程。

本模式的 SQLite 与 Milvus Lite 是单进程开发存储；不要另外启动 `operation-worker`，也不要和
Docker 数据卷混用。

## 2. Docker 本地验证

前提：Docker Desktop 已运行，且 `docker compose version` 可用。首次创建根目录 `.env`：

```bash
cp env.docker.example .env
# 至少填写 POSTGRES_PASSWORD、JWT_SECRET；BYOK_REQUIRED=false 时再填写模型和 Embedding Key。
./scripts/deploy.sh
```

脚本显式合并 `docker-compose.yml` 与 `docker-compose.override.yml`，本地才会发布前端、后端和诊断
端口。它会先检查 Compose 配置，再构建、启动并打印容器状态；默认不会启动 Nginx。

```bash
# 只构建、更新后端及其依赖
./scripts/deploy.sh backend

# 查看容器和日志
docker compose ps
./scripts/logs.sh backend

# 停止容器，保留数据库和索引数据
docker compose down
```

请勿在日常停机时使用 `docker compose down -v`，它会删除 PostgreSQL、Qdrant 等命名卷中的数据。

### 启用图谱检索

在根目录 `.env` 设置下面的值；`--kg` 会启用 Compose 内置的预检，缺失的图谱密钥会在 Neo4j/LightRAG
启动前明确失败。

```dotenv
NEO4J_PASSWORD=<strong-password>
LIGHTRAG_API_KEY=<random-api-key>
LIGHTRAG_ENABLED=true
LIGHTRAG_BASE_URL=http://lightrag:9621
```

然后启动：

```bash
./scripts/deploy.sh --kg
```

本地覆盖层会另外发布 Neo4j Browser（<http://localhost:7474>）和 LightRAG（<http://localhost:9621>）。
它们用于诊断；产品内的知识图谱查看页面仍是日常使用入口。

## 3. HTTPS 生产部署

生产机器应只使用基础 Compose 文件。DNS、反向代理权限和证书签发是部署前置条件；现有 Nginx 模板会
读取主机的 `/etc/letsencrypt/live/$DOMAIN/` 证书，因此证书必须先可用。

```bash
cp env.docker.example .env
# 设置强随机 POSTGRES_PASSWORD、JWT_SECRET，及实际 DOMAIN、PUBLIC_URL=https://example.com。
./scripts/deploy.sh --production
```

生产模式只发布 Nginx 的 `80/443`，数据库、Qdrant、后端与前端仍只留在 Compose 内网。启动后：

```bash
docker compose -f docker-compose.yml --profile production ps
curl -fsS https://example.com/health
```

需要图谱检索时使用 `./scripts/deploy.sh --production --kg`，并按上一节配置图谱变量和 LightRAG 的
模型/Embedding 凭据。生产部署前将 `BYOK_REQUIRED`、模型提供商、限流、管理员和观测配置按实际安全策略
填入根目录 `.env`；不要提交该文件。

## 常用运维命令

```bash
# 本地 Docker 堆栈
docker compose ps
docker compose logs -f --tail=100 backend

# 生产 Docker 堆栈（不要加载本地 override）
docker compose -f docker-compose.yml --profile production ps
docker compose -f docker-compose.yml --profile production logs -f --tail=100 backend
```

备份和恢复命令及其停机语义见项目根目录 README 的“备份与恢复”章节。恢复会覆盖持久化数据，只能在
经过验证的备份上执行。
