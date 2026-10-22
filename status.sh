#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
detect_compose
compose ps
printf '\nHealth:\n'
for service in mysql backend frontend nginx; do printf '%-10s %s\n' "$service" "$(container_health "$service")"; done
if curl -fsS http://127.0.0.1:9999/ >/dev/null; then ok 'Application HTTP endpoint is reachable.'; else warn 'Application HTTP endpoint is not reachable.'; fi
