#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
detect_compose
if [[ "${1:-}" == --purge ]]; then
  read -r -p 'This permanently deletes the MySQL volume. Type PURGE to continue: ' answer
  [[ "$answer" == PURGE ]] || die 'Purge cancelled.'
  compose down -v
  ok 'Stack and MySQL volume removed.'
elif [[ $# -eq 0 ]]; then
  compose down
  ok 'Stack removed; MySQL volume and runtime data were preserved.'
else
  die 'Usage: ./uninstall.sh [--purge]'
fi
