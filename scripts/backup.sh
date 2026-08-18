#!/usr/bin/env bash
# Create a complete, recoverable Agenora backup.
#
# Usage:
#   AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME=1 ./scripts/backup.sh [directory]
#
# PostgreSQL uses pg_dump for a transaction-consistent logical backup. Neo4j
# Community only supports offline dumps, so the explicit environment flag is a
# deliberate acknowledgement of the short graph-service maintenance window.
set -euo pipefail

cd "$(dirname "$0")/.."

DEST_PARENT="${1:-./backups}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DEST_PARENT"
DEST_DIR="$(realpath "$DEST_PARENT")/agenora-$STAMP"
mkdir "$DEST_DIR"
chmod 700 "$DEST_DIR"

require_running() {
  local service="$1"
  if ! docker compose ps --status running -q "$service" | grep -q .; then
    echo "ERROR: Docker Compose service '$service' must be running." >&2
    exit 1
  fi
}

archive_volume() {
  local volume="$1"
  local filename="$2"
  docker run --rm \
    -v "$volume":/source:ro \
    -v "$DEST_DIR":/backup \
    alpine:3.20 \
    tar czf "/backup/$filename" -C /source .
}

require_running postgres

echo "==> PostgreSQL logical dump"
docker compose exec -T postgres sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  >"$DEST_DIR/postgres.dump"

echo "==> Backend and LightRAG data volumes"
archive_volume agenora_backend-data backend-data.tgz
archive_volume agenora_lightrag-data lightrag-data.tgz
archive_volume agenora_lightrag-inputs lightrag-inputs.tgz

if docker compose ps --status running -q neo4j | grep -q .; then
  if [[ "${AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME:-}" != "1" ]]; then
    echo "ERROR: Neo4j Community requires an offline dump." >&2
    echo "Re-run with AGENORA_BACKUP_ALLOW_NEO4J_DOWNTIME=1 to allow a short Neo4j stop." >&2
    exit 1
  fi
  echo "==> Stopping Neo4j for its required offline dump"
  docker compose stop neo4j
  restart_neo4j=1
else
  restart_neo4j=0
fi

cleanup() {
  if [[ "$restart_neo4j" == "1" ]]; then
    echo "==> Restarting Neo4j"
    docker compose start neo4j || true
  fi
}
trap cleanup EXIT

echo "==> Neo4j offline dumps (system + neo4j)"
docker run --rm \
  -v agenora_neo4j-data:/data \
  -v "$DEST_DIR":/backups \
  neo4j:5.26-community \
  neo4j-admin database dump system --to-path=/backups --overwrite-destination=true
docker run --rm \
  -v agenora_neo4j-data:/data \
  -v "$DEST_DIR":/backups \
  neo4j:5.26-community \
  neo4j-admin database dump neo4j --to-path=/backups --overwrite-destination=true

printf '%s\n' \
  "format=agenora-backup-v2" \
  "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "postgres=pg_dump custom" \
  "neo4j=offline dumps: system,neo4j" \
  >"$DEST_DIR/MANIFEST"
(cd "$DEST_DIR" && shasum -a 256 postgres.dump backend-data.tgz lightrag-data.tgz \
  lightrag-inputs.tgz system.dump neo4j.dump >SHA256SUMS)

echo "Backup complete: $DEST_DIR"
