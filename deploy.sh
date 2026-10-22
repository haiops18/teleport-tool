#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

failed_step='initialization'
on_error() {
  local code=$?
  printf '[ERROR] Deployment failed at step: %s\n' "$failed_step" >&2
  [[ -n "${COMPOSE[*]:-}" ]] && show_diagnostics
  exit "$code"
}
trap on_error ERR

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
  elif [[ -r /dev/urandom ]]; then od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
  else die 'Cannot generate secure secrets: openssl and /dev/urandom are unavailable.'
  fi
}
set_env_value() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp .env.XXXXXX)"
  awk -v key="$key" -v value="$value" 'BEGIN { done=0 } $0 ~ "^" key "=" { print key "=" value; done=1; next } { print } END { if (!done) print key "=" value }' .env > "$tmp"
  mv "$tmp" .env
}
env_value() { sed -n "s/^$1=//p" .env | tail -n 1; }
prepare_env() {
  if [[ ! -f .env ]]; then
    info 'No .env found; creating one with securely generated local secrets.'
    cp .env.example .env
    local db user password root_password app_secret
    db="$(env_value MYSQL_DATABASE)"; user="$(env_value MYSQL_USER)"
    password="$(generate_secret)"; root_password="$(generate_secret)"; app_secret="$(generate_secret)$(generate_secret)"
    set_env_value MYSQL_PASSWORD "$password"
    set_env_value MYSQL_ROOT_PASSWORD "$root_password"
    set_env_value APP_SECRET "$app_secret"
    set_env_value DATABASE_URL "mysql+pymysql://${user}:${password}@mysql:3306/${db}"
    chmod 600 .env
    ok 'Created .env with generated secrets (not printed).'
  else
    info 'Using existing .env; existing secrets will not be changed.'
  fi
  local key value
  for key in MYSQL_DATABASE MYSQL_USER MYSQL_PASSWORD MYSQL_ROOT_PASSWORD DATABASE_URL APP_SECRET; do
    value="$(env_value "$key")"
    [[ -n "$value" && "$value" != *CHANGE_ME* ]] || die ".env contains an empty or placeholder value for $key."
  done
}
load_image() {
  local name="$1" archive="$2"
  [[ -f "$archive" ]] || die "Missing bundled image: $archive"
  info "Loading $name image..."
  docker load -i "$archive" >/dev/null
  ok "$name image loaded."
}

failed_step='checking Docker and Compose'
info 'Checking Docker...'
detect_compose
ok "Docker and ${COMPOSE[*]} are available."

failed_step='preparing environment'
prepare_env

failed_step='loading bundled Docker images'
load_image backend images/backend.tar
load_image frontend images/frontend.tar
load_image mysql images/mysql.tar
load_image nginx images/nginx.tar
for image in teleport-cgroup-scanner-backend:local teleport-cgroup-scanner-frontend:local mysql:8.4 nginx:1.27-alpine; do
  docker image inspect "$image" >/dev/null || die "Loaded image is missing: $image"
done
ok 'All required images are present.'

failed_step='creating runtime directories'
mkdir -p data/sessions data/exports backup
# The backend runs as UID 10001. Use an image-local root process so deployment
# also works for a non-root user who has Docker access.
docker run --rm --user 0 -v "$SCRIPT_DIR/data:/data" teleport-cgroup-scanner-backend:local sh -c 'mkdir -p /data/sessions /data/exports && chown -R 10001:10001 /data && chmod 700 /data/sessions /data/exports' >/dev/null
ok 'Runtime directories are ready.'

failed_step='validating bundled tsh binaries'
for tsh in tsh/13.4/tsh tsh/14.4/tsh tsh/16.4/tsh; do
  [[ -x "$tsh" ]] || die "Missing or non-executable tsh binary: $tsh"
  version_home="$(mktemp -d)"
  HOME="$version_home" TELEPORT_HOME="$version_home" "$tsh" version --skip-version-check >/dev/null
  rm -rf "$version_home"
done
ok 'Bundled tsh binaries are executable and version-verified.'

failed_step='validating Docker Compose configuration'
compose config >/dev/null || die 'docker-compose.yml validation failed.'
ok 'docker-compose.yml is valid.'

failed_step='starting MySQL'
info 'Starting MySQL...'
compose up -d mysql
wait_for_health mysql 180 || die 'MySQL did not become healthy within 180 seconds.'

# MySQL 8.4 starts a temporary initialization server during first boot.  The
# healthcheck uses TCP, and this explicit TCP query additionally proves that
# the final server is accepting database queries before migrations begin.
failed_step='waiting for MySQL TCP readiness'
mysql_ready=false
for _ in $(seq 1 90); do
  if compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -h 127.0.0.1 -P 3306 -uroot "$MYSQL_DATABASE" -Nse "SELECT 1"' >/dev/null 2>&1; then
    mysql_ready=true
    break
  fi
  sleep 2
done
[[ "$mysql_ready" == true ]] || die 'MySQL did not accept TCP database queries within 180 seconds.'
ok 'MySQL accepts TCP database queries.'

failed_step='applying database migrations'
bash mysql/migrate.sh

failed_step='starting application stack'
info 'Starting backend, frontend, and nginx...'
compose up -d
for service in mysql backend frontend nginx; do
  failed_step="waiting for $service healthcheck"
  wait_for_health "$service" 180 || die "$service did not become healthy within 180 seconds."
done

failed_step='checking application HTTP endpoint'
curl -fsS http://127.0.0.1:9999/ >/dev/null
ok 'Application HTTP endpoint is reachable.'

server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '\n========================================\nTeleport Cgroup Scanner deployed\n========================================\n'
for service in mysql backend frontend nginx; do printf '%-10s %s\n' "$service" "$(container_health "$service")"; done
printf '\nApplication:\nhttp://localhost:9999\nhttp://%s:9999\n\nCommands:\n./status.sh\n./restart.sh\n./stop.sh\n' "${server_ip:-<server-ip>}"
