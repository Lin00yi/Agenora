#!/usr/bin/env bash
# Restore one backup created by scripts/backup.sh.
#
# This intentionally destructive operation requires an exact acknowledgement:
#   AGENORA_RESTORE_CONFIRM=RESTORE_AGENORA ./scripts/restore.sh backups/agenora-...
set -euo pipefail

if [[ "${AGENORA_RESTORE_CONFIRM:-}" != "RESTORE_AGENORA" ]]; then
  echo "Refusing destructive restore. Set AGENORA_RESTORE_CONFIRM=RESTORE_AGENORA." >&2
  exit 2
fi
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  exit 2
fi

cd "$(dirname "$0")/.."
BACKUP_DIR=$(realpath "$1")
for required in MANIFEST SHA256SUMS postgres.dump backend-data.tgz lightrag-data.tgz \
  lightrag-inputs.tgz system.dump neo4j.dump; do
  [[ -f "$BACKUP_DIR/$required" ]] || {
    echo "ERROR: missing backup artifact: $required" >&2
    exit 1
  }
done
(cd "$BACKUP_DIR" && shasum -a 256 -c SHA256SUMS)

restore_volume() {
  local volume="$1"
  local filename="$2"
  docker run --rm \
    -v "$volume":/target \
    -v "$BACKUP_DIR":/backup:ro \
    alpine:3.20 \
    sh -ceu "rm -rf /target/* /target/.[!.]* /target/..?*; tar xzf /backup/$filename -C /target"
}

echo "==> Stopping application services"
docker compose stop nginx frontend backend lightrag neo4j postgres || true

echo "==> Restoring backend and LightRAG volumes"
restore_volume agenora_backend-data backend-data.tgz
restore_volume agenora_lightrag-data lightrag-data.tgz
restore_volume agenora_lightrag-inputs lightrag-inputs.tgz

echo "==> Restoring Neo4j offline dumps"
docker run --rm \
  -v agenora_neo4j-data:/data \
  -v "$BACKUP_DIR":/backups:ro \
  neo4j:5.26-community \
  neo4j-admin database load system --from-path=/backups --overwrite-destination=true
docker run --rm \
  -v agenora_neo4j-data:/data \
  -v "$BACKUP_DIR":/backups:ro \
  neo4j:5.26-community \
  neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true

echo "==> Starting PostgreSQL and restoring its logical dump"
docker compose up -d postgres
until docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; do
  sleep 2
done
docker compose exec -T postgres sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
  <"$BACKUP_DIR/postgres.dump"

echo "==> Starting full stack"
docker compose up -d
echo "Restore complete. Verify with: docker compose ps && docker compose exec backend curl -fsS http://localhost:8000/health"
