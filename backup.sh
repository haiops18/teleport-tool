#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
detect_compose
mkdir -p backup
timestamp="$(date +%Y%m%d-%H%M%S)"
outfile="backup/mysql_${timestamp}.sql.gz"
info "Writing MySQL backup to $outfile"
compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --events "$MYSQL_DATABASE"' | gzip -c > "$outfile"
chmod 600 "$outfile"
cp .env "backup/env_${timestamp}" && chmod 600 "backup/env_${timestamp}"
ok "Backup created: $outfile"
