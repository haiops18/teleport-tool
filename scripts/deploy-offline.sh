#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$ROOT_DIR/project}"
cd "$PROJECT_DIR"
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin is required" >&2; exit 1; }
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Set strong secrets, then rerun." >&2
  exit 2
fi
mkdir -p data/sessions data/exports
chmod 700 data/sessions data/exports || true
for image in "$ROOT_DIR"/images/*.tar "$ROOT_DIR"/project/images/*.tar; do
  [[ -f "$image" ]] || continue
  docker load -i "$image"
done
docker compose up -d --no-build
docker compose ps
echo "Waiting for health checks..."
for i in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:9999/ >/dev/null 2>&1; then
    echo "Teleport Cgroup Scanner is available at http://$(hostname -I | awk '{print $1}'):9999"
    exit 0
  fi
  sleep 3
done
docker compose ps
echo "Deployment started but health verification timed out; inspect docker compose logs." >&2
exit 1
