#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
detect_compose
compose restart
for service in mysql backend frontend nginx; do wait_for_health "$service" 180 || die "$service did not become healthy after restart."; done
ok 'Stack restarted.'
