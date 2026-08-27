#!/usr/bin/env bash
# Agenora 部署 — 明确选择本地或生产 Compose 编排，再构建并更新容器。
# 用法：
#   ./scripts/deploy.sh [--kg] [service ...]       本地 Docker 调试（默认）
#   ./scripts/deploy.sh --production [--kg]        生产 HTTPS 编排
#   ./scripts/deploy.sh --help
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy.sh [--kg] [service ...]       Local Docker verification (default)
  ./scripts/deploy.sh --production [--kg]        Production HTTPS stack
  ./scripts/deploy.sh --help
EOF
}

MODE="local"
KG_ENABLED="false"
SERVICES=()

while (($#)); do
  case "$1" in
    --production)
      MODE="production"
      ;;
    --kg)
      KG_ENABLED="true"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "✗ Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      SERVICES+=("$1")
      ;;
  esac
  shift
done

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 is required. Install and start Docker Desktop first." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "✗ .env not found. Copy env.docker.example to .env and fill in secrets first." >&2
  exit 1
fi

COMPOSE_FILES=(-f docker-compose.yml)
if [[ "$MODE" == "local" ]]; then
  COMPOSE_FILES+=(-f docker-compose.override.yml)
fi

COMPOSE_PROFILES=()
if [[ "$MODE" == "production" ]]; then
  COMPOSE_PROFILES+=(--profile production)
fi
if [[ "$KG_ENABLED" == "true" ]]; then
  COMPOSE_PROFILES+=(--profile kg)
fi

compose() {
  docker compose "${COMPOSE_FILES[@]}" "${COMPOSE_PROFILES[@]}" "$@"
}

SERVICE_LABEL="all services"
if ((${#SERVICES[@]})); then
  SERVICE_LABEL="${SERVICES[*]}"
fi

echo "==> Validating ${MODE} Compose configuration..."
compose config --quiet

echo "==> Building ${SERVICE_LABEL}..."
compose build "${SERVICES[@]}"

echo "==> Bringing stack up..."
compose up -d --remove-orphans "${SERVICES[@]}"

echo "==> Status:"
compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo
echo "==> Recent backend logs:"
compose logs --tail=15 backend 2>&1 | tail -20

echo
if [[ "$MODE" == "local" ]]; then
  echo "Done. Frontend: http://localhost:3000  Backend health: http://localhost:8000/health"
else
  echo "Done. Verify the PUBLIC_URL configured in .env after its TLS certificate is available."
fi
