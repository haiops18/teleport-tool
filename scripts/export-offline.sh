#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/../teleport-cgroup-scanner-offline-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT_DIR/images" "$OUT_DIR/project"
cd "$ROOT_DIR"
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
docker compose build backend frontend
docker pull mysql:8.4
docker pull nginx:1.27-alpine
docker save -o "$OUT_DIR/images/teleport-cgroup-scanner-backend.tar" teleport-cgroup-scanner-backend:local
docker save -o "$OUT_DIR/images/teleport-cgroup-scanner-frontend.tar" teleport-cgroup-scanner-frontend:local
docker save -o "$OUT_DIR/images/mysql-8.4.tar" mysql:8.4
docker save -o "$OUT_DIR/images/nginx-1.27-alpine.tar" nginx:1.27-alpine
rsync -a --delete --exclude '.env' --exclude 'data/sessions/*' --exclude 'data/exports/*' --exclude '.git' --exclude 'frontend/node_modules' --exclude 'frontend/dist' "$ROOT_DIR/" "$OUT_DIR/project/"
cp "$ROOT_DIR/.env.example" "$OUT_DIR/project/.env.example"
cp "$ROOT_DIR/scripts/deploy-offline.sh" "$OUT_DIR/deploy-offline.sh"
chmod +x "$OUT_DIR/deploy-offline.sh"
tar -C "$(dirname "$OUT_DIR")" -czf "${OUT_DIR}.tar.gz" "$(basename "$OUT_DIR")"
echo "Bundle: ${OUT_DIR}.tar.gz"
