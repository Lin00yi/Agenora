#!/usr/bin/env bash
# Agenora 备份 — 打包 PostgreSQL volume + backend data volume 成 tarball。
# 用法：
#   ./scripts/backup.sh                  备份到 ./backups/agenora-*-YYYY-MM-DD.tgz
#   ./scripts/backup.sh /mnt/backups     备份到指定目录
#
# Volume names remain anykb_* for backward compatibility with existing installs.
set -euo pipefail

cd "$(dirname "$0")/.."

DEST_DIR="${1:-./backups}"
mkdir -p "$DEST_DIR"

STAMP=$(date +%F-%H%M)
PG_OUT="$DEST_DIR/agenora-pg-$STAMP.tgz"
DATA_OUT="$DEST_DIR/agenora-data-$STAMP.tgz"

echo "==> Backing up postgres volume → $PG_OUT"
docker run --rm \
  -v anykb_postgres-data:/src:ro \
  -v "$(realpath "$DEST_DIR")":/dst \
  alpine tar czf "/dst/agenora-pg-$STAMP.tgz" -C /src .

echo "==> Backing up backend data volume (Milvus Lite + uploads) → $DATA_OUT"
docker run --rm \
  -v anykb_backend-data:/src:ro \
  -v "$(realpath "$DEST_DIR")":/dst \
  alpine tar czf "/dst/agenora-data-$STAMP.tgz" -C /src .

echo
echo "Done:"
ls -lh "$PG_OUT" "$DATA_OUT"
