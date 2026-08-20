# Operation worker 与数据生命周期

所有耗时后台动作通过 `operation_jobs` 进入同一套控制面：`ingest_document`、`kb_rebuild`、`memory_heavy`、`memory_maintenance`、`sync_lightrag_document`、`kb_regression` 与 `retention_sweep`。每个任务包含 payload、幂等键、可用时间、租约 token、重试次数、结果和死信状态；HTTP 的 `BackgroundTasks` 只会尝试立即唤醒已提交任务，进程重启后由 `operation-worker` 继续恢复。

Docker Compose 默认运行：

```bash
docker compose logs -f operation-worker
```

保留策略通过环境变量配置：`TRACE_RETENTION_DAYS=90`、`EVAL_RUN_RETENTION_DAYS=365`、`OPERATION_JOB_RETENTION_DAYS=14`。会话正文和 `documents.parsed_text` 默认不自动清理，只有显式设置 `CONVERSATION_RETENTION_DAYS` 或 `PARSED_TEXT_RETENTION_DAYS` 才会删除。Trace 归档是可选项：开启 `TRACE_ARCHIVE_ENABLED=true` 后，删除热数据库 Trace 前写入对象存储的 `trace-archive/` 前缀；生产对象存储必须对此 prefix 设置独立生命周期规则。

评测的 `retrieval.jsonl` 位于对象存储 `eval-runs/<kb>/<run>.jsonl`，不再依赖 API 容器本地卷。删除 KB 会同时删除该 KB 的对象存储评测产物；历史本地文件仅作为一次升级兼容读取路径。
