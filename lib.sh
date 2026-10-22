#!/usr/bin/env bash
# Shared, shellcheck-friendly helpers for the offline deployment scripts.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

detect_compose() {
  command -v docker >/dev/null 2>&1 || die 'Docker is not installed.'
  if ! docker info >/dev/null 2>&1; then
    die 'Docker is installed but current user has no permission, or the Docker daemon is unavailable.'
  fi
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die 'Docker Compose is not installed.'
  fi
}

compose() { "${COMPOSE[@]}" "$@"; }

container_health() {
  local service="$1" id state
  id="$(compose ps -q "$service" 2>/dev/null || true)"
  [[ -n "$id" ]] || { printf 'missing'; return; }
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || true)"
  printf '%s' "${state:-unknown}"
}

wait_for_health() {
  local service="$1" timeout="${2:-180}" elapsed=0 state
  while (( elapsed < timeout )); do
    state="$(container_health "$service")"
    [[ "$state" == healthy ]] && { ok "$service is healthy"; return 0; }
    [[ "$state" == unhealthy || "$state" == exited || "$state" == dead ]] && return 1
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

show_diagnostics() {
  warn 'Current stack status:'
  compose ps || true
  warn 'Recent container logs:'
  compose logs --tail=100 || true
}
