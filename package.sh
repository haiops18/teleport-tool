#!/usr/bin/env bash
# Build a deployable, offline .tar from the exact images currently on this host.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
VERSION="${1:-$(date +%Y%m%d-%H%M%S)}"
PACKAGE_NAME="teleport-cgroup-scanner-${VERSION}"
DIST_DIR="$ROOT_DIR/dist"
OUTPUT_TAR="$DIST_DIR/${PACKAGE_NAME}.tar"
mkdir -p "$DIST_DIR"
STAGING_PARENT="$(mktemp -d "$DIST_DIR/.staging.XXXXXX")"
STAGING="$STAGING_PARENT/teleport-cgroup-scanner"
cleanup() { rm -rf "$STAGING_PARENT"; }
trap cleanup EXIT

info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[OK] %s\n' "$*"; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die 'Docker is not installed.'
docker info >/dev/null 2>&1 || die 'Docker is installed but current user has no permission, or the Docker daemon is unavailable.'
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then COMPOSE=(docker-compose)
else die 'Docker Compose is not installed.'; fi

info 'Inspecting current running stack and images...'
"${COMPOSE[@]}" ps
for image in teleport-cgroup-scanner-backend:local teleport-cgroup-scanner-frontend:local mysql:8.4 nginx:1.27-alpine; do
  docker image inspect "$image" >/dev/null || die "Required image is unavailable: $image"
done
for tsh in tsh/13.4/tsh tsh/14.4/tsh tsh/16.4/tsh; do
  [[ -x "$tsh" ]] || die "Required executable is unavailable: $tsh"
  file "$tsh" | grep -q 'ELF.*executable' || die "Invalid tsh executable: $tsh"
  version_home="$(mktemp -d)"
  HOME="$version_home" TELEPORT_HOME="$version_home" "$tsh" version --skip-version-check >/dev/null
  rm -rf "$version_home"
done

git_commit='N/A'
if git rev-parse HEAD >/dev/null 2>&1; then git_commit="$(git rev-parse HEAD)"; fi
mkdir -p "$STAGING/images" "$STAGING/mysql/migrations" "$STAGING/nginx" "$STAGING/tsh" "$STAGING/data/sessions" "$STAGING/data/exports"
cp -a .env.example "$STAGING/.env.example"
cp -a docker-compose.offline.yml "$STAGING/docker-compose.yml"
cp -a OFFLINE_DEPLOYMENT_README.md "$STAGING/README.md"
cp -a deploy.sh stop.sh restart.sh status.sh uninstall.sh backup.sh lib.sh "$STAGING/"
cp -a mysql/init.sql mysql/migrate.sh "$STAGING/mysql/"
cp -a mysql/migrations/. "$STAGING/mysql/migrations/"
cp -a nginx/nginx.conf "$STAGING/nginx/"
cp -a tsh/. "$STAGING/tsh/"
touch "$STAGING/data/sessions/.gitkeep" "$STAGING/data/exports/.gitkeep"
chmod 700 "$STAGING/data/sessions" "$STAGING/data/exports"
chmod +x "$STAGING"/{deploy,stop,restart,status,uninstall,backup,lib}.sh "$STAGING/mysql/migrate.sh"

info 'Saving current Docker images; no build or pull will be performed...'
docker save -o "$STAGING/images/backend.tar" teleport-cgroup-scanner-backend:local
docker save -o "$STAGING/images/frontend.tar" teleport-cgroup-scanner-frontend:local
docker save -o "$STAGING/images/mysql.tar" mysql:8.4
docker save -o "$STAGING/images/nginx.tar" nginx:1.27-alpine

cat > "$STAGING/BUILD_INFO.txt" <<EOF
Build Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Git Commit: $git_commit
Backend Image: $(docker image inspect teleport-cgroup-scanner-backend:local --format '{{index .RepoTags 0}} {{.Id}}')
Frontend Image: $(docker image inspect teleport-cgroup-scanner-frontend:local --format '{{index .RepoTags 0}} {{.Id}}')
Nginx Image: $(docker image inspect nginx:1.27-alpine --format '{{index .RepoTags 0}} {{.Id}}')
MySQL Image: $(docker image inspect mysql:8.4 --format '{{index .RepoTags 0}} {{.Id}}')
Compose File: docker-compose.yml (offline, no build directives)
Application Version: $VERSION
EOF

tar -C "$STAGING_PARENT" -cf "$OUTPUT_TAR" teleport-cgroup-scanner
(cd "$DIST_DIR" && sha256sum "${PACKAGE_NAME}.tar" > "${PACKAGE_NAME}.tar.sha256")
ok "Package created: $OUTPUT_TAR"
ok "Checksum created: ${OUTPUT_TAR}.sha256"
