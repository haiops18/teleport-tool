#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
detect_compose
compose stop
ok 'Stack stopped; MySQL volume and runtime data were preserved.'
