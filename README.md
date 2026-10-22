# Teleport Cgroup Scanner — v1.0.0

> **Tiếng Việt:** Công cụ vận hành nội bộ cho Teleport, hỗ trợ quét rủi ro
> cgroup của `teleport.service`, kiểm tra/cấu hình KillMode, khám phá Compute
> qua LLDP, jobs nền, báo cáo và Excel export. Không lưu password/OTP Teleport
> vào database hoặc frontend.
>
> **English:** An internal Teleport operations tool for `teleport.service`
> cgroup risk scanning, KillMode checks/configuration, LLDP Compute Discovery,
> background jobs, reporting, and Excel exports. Teleport passwords and OTPs
> are never stored in the database or frontend.

## Vietnamese — Hướng dẫn v1.0

### Chức năng chính

- Đăng nhập Teleport qua `tsh` theo phiên riêng biệt.
- Đồng bộ Nodes, quét process trong cgroup `teleport.service` theo batch nền.
- Kiểm tra/cấu hình `KillMode`; thao tác cấu hình/restart yêu cầu quyền Admin
  và xác nhận gõ `APPLY CONFIGURATION`.
- Compute Discovery qua LLDP: tìm NIC vật lý phù hợp, ghi compute host, lý do
  `NOT_DETECTED` hoặc lỗi kỹ thuật theo từng node.
- Jobs nền cho Cgroup Scan, Service Check/Configure và Compute Discovery.
- Báo cáo theo session, phân trang/search server-side, nhóm Nodes theo Compute,
  Excel gồm summary, compute groups, nodes, not-detected, history và job details.
- RBAC server-side: `VIEWER`, `OPERATOR`, `ADMIN`; audit log cho hành động vận hành.

### Kiến trúc

```text
Browser -> Nginx :9999 -> React frontend -> FastAPI -> MySQL
                                      -> tsh -> Teleport Proxy -> Nodes
```

MySQL chỉ nằm trong internal network. Backend có egress network riêng để truy
cập Teleport Proxy.

### Yêu cầu

- Linux amd64, Docker Engine và Docker Compose v2.
- `tsh` tương thích trong `tsh/13.4`, `tsh/14.4`, `tsh/16.4`.
- Quyền Teleport cho phép liệt kê node và thực thi lệnh read-only trên node.
- Với production: TLS/certificate tại Nginx hoặc load balancer phía trước.

### Cài đặt / nâng cấp

```bash
cp .env.example .env
# Chỉnh MySQL credentials, APP_SECRET và RBAC users; không commit file .env.

# Chỉ chạy với source deployment khi cần build locally:
docker compose build
docker compose up -d

# Với release image đã build/tag sẵn:
docker compose up -d --no-build
docker compose ps
```

Truy cập: `http://SERVER_IP:9999`.

Sau upgrade schema hiện hữu, chạy migration additive/idempotent:

```bash
bash mysql/migrate.sh
```

Migration không drop table, không xoá data. `mysql/init.sql` chỉ chạy khi MySQL
volume mới; database đang tồn tại phải dùng migration.

### Cấu hình RBAC

```dotenv
ADMIN_USERS=admin@example.com
OPERATOR_USERS=operator1@example.com,operator2@example.com
DEFAULT_ROLE=VIEWER
SESSION_TTL_HOURS=12
```

- **Viewer:** xem Nodes, Jobs, Reports và export.
- **Operator:** Viewer + Cgroup Scan, Compute Discovery, Service Check.
- **Admin:** Operator + Apply/Rollback Service Configuration, restart và xoá report.

Frontend chỉ hỗ trợ UX; quyền luôn được kiểm tra ở FastAPI. API không có session
trả `401`, role không đủ trả `403`.

### Vận hành và an toàn

```bash
./status.sh
./backup.sh
./restart.sh
./stop.sh
./uninstall.sh        # không xoá volume
./uninstall.sh --purge # yêu cầu xác nhận, xoá volume
```

- Backup tạo MySQL dump và backup `.env` với permission hạn chế.
- Job `QUEUED`/`RUNNING` bị mồ côi sau backend restart được đánh dấu `FAILED`;
  dữ liệu kết quả cũ không bị xoá.
- Không commit `.env`, `data/sessions`, exports, backup, `tsh` credential,
  private key hoặc token.
- Không expose MySQL port ra host.

### Xử lý sự cố

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f mysql
curl -fsS http://127.0.0.1:9999/api/health
```

Nếu rollback release, giữ image/version compose cũ, restore compose cũ và
recreate backend/frontend. Chỉ restore MySQL dump khi sự cố liên quan schema/data.

---

## English — Detailed technical documentation

## Compute Discovery background jobs

Compute Discovery submits selected Teleport node IDs to `POST /api/compute-discovery/jobs` and returns a job immediately. The backend runs the existing read-only LLDP capture in bounded background batches, stores an immutable result per node/job, and updates progress after every node. `Running Job` includes `COMPUTE DISCOVERY`; its detail view polls only while the job is `QUEUED` or `RUNNING`.

Discovery report data is session-scoped and read-only. It has server-paginated Compute Groups, Nodes (latest state), and History views. The Excel export contains `01_Summary`, `02_Compute_Groups`, `03_Nodes`, `04_Discovery_History`, and `05_Job_Details`; untrusted cell values are protected from formula injection.

For an existing database, run `bash mysql/migrate.sh` after MySQL is healthy. Migration `007_compute_discovery_jobs` is additive/idempotent: it preserves legacy discovery rows, attaches rows with no job to a synthetic migrated job, and then enforces the result-to-job foreign key. Discovery tuning variables are `DISCOVERY_MAX_CONCURRENCY`, `DISCOVERY_BATCH_SIZE`, `DISCOVERY_MAX_NODES_PER_REQUEST`, and `DISCOVERY_SCAN_TIMEOUT_SECONDS`.

Internal, read-only web tool that uses a version-specific `tsh` binary to enumerate Teleport nodes and identify non-Teleport processes inside the `teleport.service` cgroup. These processes can be terminated when the service is restarted.

## Architecture

`Browser -> Nginx -> React / FastAPI -> MySQL` and `FastAPI -> selected tsh -> Teleport Proxy -> node`. MySQL and the application network are internal. Backend additionally has a dedicated egress network because it must reach the Teleport proxy; MySQL does not.

## Folder structure

```text
backend/       FastAPI API, Teleport/session/scan/export services
frontend/      React + TypeScript Vite interface
mysql/init.sql Database schema
nginx/         Reverse-proxy configuration
tsh/           One executable tsh binary per version
data/sessions/ Per-login TELEPORT_HOME directories (not committed)
data/exports/  Generated Excel reports (not committed)
```

## Requirements

- Docker Engine and Docker Compose v2.
- Linux amd64 `tsh` binaries compatible with target proxies.
- A Teleport role that can list nodes and run the remote read-only commands. Scanner defaults to `root@hostname`; change `backend/app/services/scanner.py` for another OS login.

## Installation

```bash
cp .env.example .env
# edit every CHANGE_ME value
install -m 755 /path/to/tsh-13.4 tsh/13.4/tsh
install -m 755 /path/to/tsh-14.4 tsh/14.4/tsh
install -m 755 /path/to/tsh-16.4 tsh/16.4/tsh
docker compose build
docker compose up -d
docker compose ps
```

Open `http://SERVER_IP:9999/`. Configure approved TLS termination before public exposure; this repository intentionally does not ship a dummy certificate.

## Configuration

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | SQLAlchemy MySQL DSN; must agree with MySQL credentials |
| `MYSQL_*` | MySQL initial database/user credentials |
| `SESSION_TTL_HOURS` | Max retained local Teleport session, default 12 |
| `SCAN_CONCURRENCY` | Max simultaneous nodes, default 10 |
| `SCAN_BATCH_SIZE` | Nodes admitted into each cgroup scan wave, default 10 |
| `SERVICE_CONFIG_MAX_CONCURRENCY` | Max simultaneous Service Config operations within a wave, default 5 |
| `SERVICE_CONFIG_BATCH_SIZE` | Nodes admitted into each Service Config wave, default 10 |
| `SSH_TIMEOUT_SECONDS` | SSH command timeout configuration |
| `SCAN_TIMEOUT_SECONDS` | Per-node scan time configuration |
| `ALLOWED_ORIGINS` | Comma-separated browser origins |

Set writable volume ownership for the non-root backend process: `chown -R 10001:10001 data`.

## Database and API

`mysql/init.sql` creates `sessions`, `nodes`, `scan_jobs`, and `scan_results`. Passwords, OTPs, certificates and private keys are never database columns.

Public routes are reverse-proxied with `/api`:

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/status`
- `GET /api/nodes`, `POST /api/nodes/refresh`, `POST /api/nodes/{id}/scan`
- `POST /api/scan`, `GET /api/scan/{job_id}`, `GET /api/scan/{job_id}/results`
- `POST /api/export/{job_id}`, `GET /api/export/{job_id}/download`
- `GET /api/history`, `GET /api/history/{job_id}`

## Teleport login and sessions

The backend calls only the selected exact path: `/opt/tsh/13.4/tsh`, `/opt/tsh/14.4/tsh`, or `/opt/tsh/16.4/tsh`. `pexpect` supplies password/OTP to interactive `tsh login` only in RAM. A cryptographically random ID creates `/data/sessions/<id>` and becomes `TELEPORT_HOME`; credentials never mix across users, clusters or tsh versions. `tsh status` is checked post-login. Logout and expiry remove the directory; expiry cleanup runs every 10 minutes.

## Node refresh and cgroup scan

Node discovery tries `tsh ls --format=json`, normalizes both legacy and resource-shaped (`metadata`/`spec`) JSON, then falls back to table parsing. A successful login immediately loads nodes. The UI persists a per-browser Auto-load setting of 1 minute, 3 minutes, 5 minutes (default), or Off; it invokes the authenticated refresh API and then reloads the table. The backend scheduler only cleans up expired sessions, so Off does not cause hidden cluster refreshes.

The remote scanner is strictly read-only: `systemctl show`, `stat`, `find`, `cat`, `ps`, `readlink`, and `tr`. It discovers `ControlGroup`, reads cgroup v2 directly and finds a cgroup v1 `cgroup.procs` fallback. It never runs kill, pkill, restart, stop, start, reboot, rm, chmod or chown on a node.

Exact excluded executable/command values are `/usr/local/bin/teleport`, `teleport`, `bash`, `/bin/bash`, and `/usr/bin/bash`; a process is not excluded merely because arguments contain “teleport”. Results are SAFE, WARNING, ERROR or UNREACHABLE. Bulk scans have a bounded worker pool.

## Excel

Export creates `data/exports/teleport_cgroup_scan_YYYYMMDD_HHMMSS.xlsx` with Summary, Scan Results and Errors sheets. It includes bold headers, frozen/filterable rows, wrapping, automatic widths and status colors.

## Report Module

Report reads historical MySQL scan data only: Browser → Nginx → React Report UI → FastAPI `/api/reports/*` → Report Service → MySQL → openpyxl → `data/exports`. It never opens SSH or starts a scan. Status is centralized: SAFE means no risk process, WARNING means a detected risk process, ERROR means scan error, and UNKNOWN means insufficient data. Report APIs are session-scoped and support summary, paginated host reporting, host history, scan detail, and whole/single-host Excel export. Apply `mysql/migrations/002_report_indexes.sql` once to an existing database before enabling large report datasets.

## Security

- Backend runs as UID 10001; tsh mount is read-only.
- Containers drop Linux capabilities and use `no-new-privileges`; there is no Docker socket, host filesystem or privileged mount.
- Passwords, OTPs and Teleport credential material are not logged or returned by API responses.
- The session ID is opaque and passed as `X-Session-Id`. Deploy behind company SSO/VPN or add application SSO before broad exposure.

## Troubleshooting

| Symptom | Check |
|---|---|
| `TSH_BINARY_NOT_FOUND` | Put executable in exact `tsh/<version>/tsh` path and `chmod 755`. |
| `LOGIN_FAILED` or `OTP_REQUIRED` | Validate proxy DNS/version, credentials and OTP. |
| `NODE_UNREACHABLE` | Validate Teleport role permits `root@hostname` and backend can reach proxy. |
| `CGROUP_NOT_FOUND` | The agent may not be systemd-managed or cgroup may not be readable. |
| MySQL unhealthy | Verify `.env` and run `docker compose logs mysql`. |

## Backup, upgrade and rollback

```bash
docker compose exec mysql mysqldump -u root -p teleport_scanner > backup.sql
tar -czf teleport-scanner-files.tgz README.md .env data/exports nginx
```

For upgrade, back up then run `docker compose build && docker compose up -d`. For rollback run `docker compose down` without `-v`, restore the previous source/image, start it again, and restore the database backup if needed. Never run `docker compose down -v` in production without explicit approval and a verified backup.

## Offline deployment on another host

On the current host, export a self-contained source/image bundle:

```bash
./scripts/export-offline.sh /tmp/teleport-cgroup-scanner-offline
```

Copy the generated `.tar.gz` to the target host and extract it. On the target host:

```bash
cd teleport-cgroup-scanner-offline/project
cp .env.example .env
vi .env                         # set unique strong secrets and target settings
cd ..
./deploy-offline.sh
```

The bundle includes backend/frontend/MySQL/nginx images, source configuration and tsh binaries. It intentionally excludes `.env`, MySQL data, Teleport sessions and generated exports. The target requires Docker Engine, Docker Compose plugin, `curl`, `awk`, and `tar`; it does not require registry access. The application is published on port 9999. Preserve the generated MySQL volume when upgrading; do not use `docker compose down -v` without a verified backup.

## Change Log

### 2026-09-28  UI Report Remove and Job Metadata

Component: Frontend / Reports / Jobs

Change: Report now supports current-page selection, Export Selected, Remove Selected and per-host removal confirmation without deleting Teleport inventory. Job list displays custom/fallback job names and uses started_at before created_at.

Files:
- frontend/src/main.tsx

Reason: Complete report data maintenance and make Service Check/Configure jobs identifiable in the running-jobs view.

Apply: `docker compose build frontend && docker compose up -d frontend nginx`

Validation: Frontend production build completed and Docker services are healthy.

Rollback: Restore the previous frontend image/source and recreate frontend/nginx.

### 2026-09-28  Job Dialogs and Job Detail UI

Component: Frontend / Service Config / Scan Jobs

Change: Service Check and Service Configure now request an optional Job Name before creating the backend job. Job detail displays Job Name, created/started/finished timestamps, Node Name, IP and service configuration fields when returned by the API.

Validation: `npm run build` completed in the frontend container; backend scanner tests passed; all Compose services reported healthy.

## Config Report

Config Report is a read-only derived view of `service_config_jobs` and `service_config_results`. It reports the latest known KillMode, configuration status, operation, Job Name, restart status and service state per node. It does not SSH to nodes, modify systemd, daemon-reload or restart Teleport.

Endpoints: `/config-report/summary`, `/config-report/nodes`, `/config-report/nodes/{node_id}`, and `/config-report/export`. The UI supports server-side search, status filtering, pagination, node selection, selected/current-filter Excel export and per-node configuration history. Latest state is based on the most recently finished service-config result; failed operations remain visible in history and are reported as ERROR.

### Service Config repeated operations

Configure/Check submissions reset selection, restart and transient feedback state after success or failure. A completed/failed/cancelled job does not block a later operation; empty selection and API errors now display feedback instead of silently returning.

### tsh 13.4 login diagnostics

The login path uses the selected version-specific binary and the same isolated `TELEPORT_HOME` for login and status. Login exit code and sanitized status errors are recorded; ANSI terminal sequences are removed. A non-zero `tsh status` is no longer incorrectly reported as `SESSION_EXPIRED` (network/proxy and client compatibility errors are reported separately). The backend does not log password, OTP, certificates or tokens.

### 2026-09-29  Dashboard UI redesign

Component: Frontend

Change: Added a dark enterprise dashboard theme with elevated cards, unified table/badge/button styling, responsive layout, clearer sidebar active states and improved spacing. The user-facing `Scan Jobs` label is now `Running Job`; the existing route/API and business logic remain unchanged.

Validation: Frontend production build completed; frontend/backend/nginx/mysql containers reported healthy.

### 2026-09-25 11:45

Component: Backend / Frontend / Teleport

Change: Load nodes immediately after login, normalize resource-style tsh JSON before persistence, return refresh counts, and add a per-browser Auto-load selector (1/3/5 minutes or Off).

Files:

- `backend/app/main.py`
- `backend/app/services/teleport.py`
- `backend/app/services/scheduler.py`
- `frontend/src/main.tsx`
- `frontend/src/style.css`

Reason: Login did not invoke `tsh ls`; the prior parser skipped resource-style JSON nodes; a fixed global five-minute scheduler could not honor Off.

Apply: `docker compose up -d --build --force-recreate backend frontend nginx`

Validation: Login reports a node count, Nodes table populates, and each Auto-load value schedules or disables authenticated refresh requests.

Rollback: Redeploy the prior backend/frontend images; existing node and scan history rows are unchanged.

### 2026-09-25 11:36

Component: Docker

Change: Published the Nginx service on host port 9999 instead of 80/443.

Files:

- `docker-compose.yml`
- `README.md`

Reason: Host port 80 is owned by the existing HAProxy service; port 9999 avoids changing that production service.

Apply: `docker compose up -d --force-recreate nginx`

Validation: `curl -fsS http://127.0.0.1:9999/health`.

Rollback: Restore the previous port mapping only after confirming that port 80 is available or a reverse-proxy route has been configured.

### 2026-09-25 11:38

Component: Docker

Change: Changed Nginx healthcheck to IPv4 loopback.

Files:

- `docker-compose.yml`

Reason: Nginx serves correctly through port 9999 but its configured listener does not bind IPv6 loopback.

Apply: `docker compose up -d --force-recreate nginx`

Validation: all four services report healthy.

Rollback: Restore `localhost` only if Nginx is explicitly configured with an IPv6 listener.

### 2026-09-25 11:24

Component: Backend / Docker / Nginx

Change: Added MySQL 8 authentication support through `cryptography` and aligned the frontend internal listener, healthcheck and reverse-proxy upstream to port 80.

Files:

- `backend/requirements.txt`
- `docker-compose.yml`
- `nginx/nginx.conf`

Reason: MySQL uses `caching_sha2_password`; frontend healthchecks had targeted a port not used by the base Nginx configuration.

Apply: `docker compose up -d --build --force-recreate backend frontend nginx`

Validation: `docker compose ps` plus `curl -fsS http://127.0.0.1/health`.

Rollback: Restore previous dependency/configuration and recreate these containers.

### 2026-09-25 11:29

Component: Docker / Nginx

Change: Restored the frontend healthcheck and Nginx upstream to port 8080, which is the listener configured by the frontend Dockerfile.

Files:

- `docker-compose.yml`
- `nginx/nginx.conf`

Reason: The frontend image remaps its Nginx listener from 80 to 8080 during build.

Apply: `docker compose up -d --force-recreate frontend nginx`

Validation: Frontend and Nginx healthchecks report healthy.

Rollback: Point both values to the listener port used by a replacement frontend image.

### 2026-09-25 11:32

Component: Docker

Change: Changed frontend healthcheck host from `localhost` to IPv4 loopback because the remapped Nginx listener does not bind IPv6.

Files:

- `docker-compose.yml`

Reason: The HTTP service was available at `127.0.0.1:8080`, while healthcheck resolution selected an unavailable IPv6 loopback listener.

Apply: `docker compose up -d --force-recreate frontend nginx`

Validation: frontend and Nginx become healthy.

Rollback: Restore `localhost` only if the frontend listens on IPv6 too.

### 2026-09-25 11:18

Component: Docker

Change: Added only the Nginx startup capabilities required to change worker ownership and bind the public port after dropping all other Linux capabilities.

Files:

- `docker-compose.yml`

Reason: Frontend Nginx could not initialize its cache directories with `cap_drop: ALL` alone.

Apply: `docker compose up -d --force-recreate frontend nginx`

Validation: `docker compose ps` shows frontend and Nginx healthy.

Rollback: Remove the listed `cap_add` entries and redeploy after moving Nginx to a non-root-compatible configuration.

### 2026-09-25 10:40

Component: Backend / Frontend / Database / Docker / Teleport

Change: Initial production-oriented implementation: version-isolated tsh login, individual credential homes, node refresh, bounded read-only scans, MySQL history, Excel exports, React UI, Nginx and healthchecks.

Files:

- `backend/`
- `frontend/`
- `mysql/init.sql`
- `nginx/nginx.conf`
- `docker-compose.yml`
- `.env.example`

Reason: Audit applications at risk from a `teleport.service` restart.

Apply: `docker compose build && docker compose up -d`

Validation: `docker compose config`, backend compile check, frontend production build.

Rollback: `docker compose down`, restore prior source/image and MySQL backup; retain database volume.

### 2026-09-25 19:40

Component: Backend / Frontend / Configuration

Change: Extended the Nodes page with database-side search (hostname, Teleport node ID, address and labels), 25/50/100 pagination, current-page selection, per-row scan actions, selected-node scan jobs, job polling, labels, last-scan timestamps and persisted 1/3/5-minute or off auto-load settings. Scan requests now deduplicate and validate IDs, enforce a configured maximum, and surface queued/scanning node states while reusing the existing bounded Teleport scan worker pool.

Files:

- `backend/app/main.py`
- `backend/app/config.py`
- `frontend/src/main.tsx`
- `frontend/src/style.css`
- `.env.example`
- `README.md`

Reason: Make the node inventory usable with large Teleport clusters without transferring all node records to the browser, and allow safe targeted scans directly from the table.

Apply: `docker compose up -d --build backend frontend nginx`

Validation: `python3 -m compileall -q backend/app backend/tests` and `cd frontend && npm run build`.

Rollback: Deploy the preceding backend/frontend images or restore the listed files from version control; no database migration is required for this change.

### 2026-09-25 22:05

Component: Database

Change: Extended `nodes.scan_status` with `QUEUED` and `SCANNING`, which are required to persist live node-scan progress.

Files:

- `mysql/init.sql`
- `mysql/migrations/003_node_scan_progress_status.sql`
- `README.md`

Reason: Existing installations used an ENUM that rejected the new progress values and caused scan submission to fail before SSH began.

Apply: `docker compose exec -T mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "ALTER TABLE nodes MODIFY scan_status ENUM('"'"'QUEUED'"'"','"'"'SCANNING'"'"','"'"'SAFE'"'"','"'"'WARNING'"'"','"'"'ERROR'"'"','"'"'UNREACHABLE'"'"') NULL"'`

Validation: Submit a single-node scan and confirm the API returns HTTP 200/`QUEUED`.

Rollback: `ALTER TABLE nodes MODIFY scan_status ENUM('SAFE','WARNING','ERROR','UNREACHABLE') NULL` only after confirming no rows retain a progress status.

### 2026-09-25 22:20

Component: Backend / Frontend

Change: Added the persistent Scan Jobs view. Each requested scan is a MySQL-backed job that continues while the user navigates the application. The view polls running jobs, displays completed/total and percentage progress, result counters, and a Stop control.

Files:

- `backend/app/main.py`
- `frontend/src/main.tsx`
- `README.md`

Reason: Operators need to submit multiple scan jobs and monitor or stop them without remaining on the Nodes page.

Apply: `docker compose up -d --build backend frontend nginx`

Validation: Create a scan, open Scan Jobs, and confirm it shows progress and permits Stop while queued/running.

Rollback: Restore the prior backend/frontend images; scan history remains intact.

### 2026-09-25 22:35

Component: Frontend

Change: Added the in-application “Nguyên tắc scan” navigation page explaining cgroup detection, read-only data collection, status definitions, exclusions, and warning behaviour.

Files:

- `frontend/src/main.tsx`
- `README.md`

Reason: Operators can verify the scanner's decision rules directly before creating a job.

Apply: `docker compose up -d --build frontend nginx`

Validation: Open the sidebar menu “Nguyên tắc scan”.

Rollback: Restore the preceding frontend image.

## Service Config

Service Config manages only the effective systemd `KillMode` for `teleport.service`. It uses a backend-defined, non-interactive drop-in at `/etc/systemd/system/teleport.service.d/override.conf`, preserves other existing override directives, creates a timestamped backup before modification, runs `systemctl daemon-reload`, and verifies `KillMode=process`. Restart is opt-in and is blocked unless a fresh effective verification reports exactly `process`. The service uses the existing session-scoped `tsh ssh root@node` transport; browser requests cannot supply shell commands or file paths.

Endpoints: `GET /api/service-config/nodes`, `POST /api/service-config/check`, `POST /api/service-config/configure`, `POST /api/service-config/rollback`, `GET /api/service-config/jobs/{job_id}`, and `GET /api/service-config/history`. Jobs and per-node audit results are stored in `service_config_jobs` and `service_config_results`; no Teleport token, unit `ExecStart`, private key, or credential is collected. Apply migration `mysql/migrations/004_service_config.sql` to existing databases before deployment.

Environment variables: `SERVICE_CONFIG_MAX_CONCURRENCY=5`, `SERVICE_CONFIG_MAX_NODES_PER_REQUEST=100`, `TELEPORT_RESTART_MAX_CONCURRENCY=2`, `TELEPORT_RESTART_RETRY_INTERVAL=5`, and `TELEPORT_RESTART_MAX_WAIT=120`.

### 2026-09-26 09:20

Component: Backend / Frontend / Database

Change: Added Service Config check, override configuration, audit job/result persistence, optional verified Teleport restart, rollback API, and Service Config page.

Files:

- `backend/app/services/service_config.py`
- `backend/app/models/models.py`
- `backend/app/schemas/api.py`
- `backend/app/main.py`
- `frontend/src/main.tsx`
- `mysql/migrations/004_service_config.sql`
- `.env.example`
- `README.md`

Reason: Centrally audit and configure `KillMode=process` to reduce the chance of unrelated cgroup processes being terminated during Teleport restart.

Apply: `docker compose exec -T mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /dev/stdin' < mysql/migrations/004_service_config.sql && docker compose up -d --build backend frontend nginx`

Validation: Backend compile check, frontend production build, and Docker healthcheck.

Rollback: Do not delete audit rows. Restore previous application image; use the Rollback operation on a node to restore a saved override when needed.

### 2026-09-26 10:05

Component: Backend / Frontend / Report

Change: Renamed the operational job view to Job Running and merged cgroup scan jobs with Service Config jobs so both progress streams are visible. Service Config restart intent is selected before configuration job creation. Report API host responses now include the most recent audited KillMode, Service Config status, timestamp, and restart status without opening a new SSH session.

Files:

- `frontend/src/main.tsx`
- `backend/app/services/report_service.py`
- `README.md`

Reason: Operators need one place to follow every long-running action and correlate scan risk with the last known Teleport service configuration.

Apply: `docker compose up -d --build backend frontend nginx`

Validation: Create a scan or Service Config job and open Job Running; verify `/api/reports/hosts/{node_id}` includes `kill_mode` and `service_config_status`.

Rollback: Restore prior frontend/backend image; history remains unchanged.

### 2026-09-26 10:25

Component: Frontend

Change: Added a View action and live per-job detail panel to Job Running. Cgroup jobs show completed scan-result rows; Service Config jobs show persisted per-node operation states. The panel polls while the selected job is running.

Files:

- `frontend/src/main.tsx`
- `README.md`

Reason: Operators can inspect each running or completed job rather than relying only on aggregate progress.

Apply: `docker compose up -d --build frontend nginx`

Validation: Open Job Running, select View for a job, and confirm the detail table refreshes while it is active.

Rollback: Restore the prior frontend image.

## Scanner Process Classification

The scanner snapshots `teleport.service` cgroup PIDs once, captures `SCANNER_PID=$$`, builds descendant sets from `/proc/<pid>/status` PPID data, and uses these classifications: `TELEPORT_CORE`, `SCAN_INTERNAL`, `TELEPORT_SESSION`, `RISK`, and `UNKNOWN`. A Teleport daemon is `TELEPORT_CORE` only when its executable and `start` invocation identify it as such. Every current descendant of a verified `/usr/local/bin/teleport exec` process is `TELEPORT_SESSION`; these active SSH session processes are excluded from risk calculation. A detached process without a current `teleport exec` ancestor remains `RISK`. Process names alone are never used to mark a process safe. `SCAN_INTERNAL`, `TELEPORT_CORE`, and `TELEPORT_SESSION` are excluded before persistence, reporting, and Excel risk counts.

The scanner protocol Base64-encodes every process command line before it crosses the SSH boundary. This prevents multi-line shell scripts or tab characters from corrupting the tab-delimited record and being incorrectly interpreted as `SAFE`.

## KillMode-aware Risk Classification

Each scan reads effective `KillMode` with `systemctl show teleport.service -p KillMode --value`. External processes remain visible. With `KillMode=process` they are saved as `EXTERNAL_PROTECTED`, make the node SAFE, and are counted separately from risks. With any other effective KillMode they are `RISK` and make the node WARNING. Active `teleport exec` trees and the current scanner tree remain excluded in both modes.

## Report Export

Report exports use authenticated binary downloads from `/api/reports/export`. GET exports the current server-side filter; POST exports validated, deduplicated selected node IDs. The workbook contains Summary, Hosts, Scan History, and Process Details, including KillMode, Classification, Risk count, and Protected External Process count. Formula-like untrusted cell values are escaped.

The exporter also removes illegal XML control characters from historical SSH error output before passing values to openpyxl. This prevents terminal ANSI/control sequences from causing Excel generation failures.

### 2026-09-28 12:00

Component: Scanner / Report / Export / Database

Change: Added effective KillMode capture to scan records, `EXTERNAL_PROTECTED` classification, protected-vs-risk reporting fields, selected-node POST export API, and Excel sanitization for historical control characters.

Files:

- `backend/app/services/scanner.py`
- `backend/app/services/report_service.py`
- `backend/app/main.py`
- `backend/app/models/models.py`
- `backend/app/schemas/api.py`
- `backend/tests/test_scanner_classification.py`
- `mysql/migrations/005_killmode_scan_results.sql`
- `README.md`

Reason: Separate external-process presence from restart kill risk, and fix report exports that failed when old SSH errors contained illegal Excel control characters.

Apply: Apply `mysql/migrations/005_killmode_scan_results.sql`, then run `docker compose up -d --build backend nginx`.

Validation: Scanner tests pass; filtered and selected report exports return XLSX MIME type and open successfully with openpyxl.

Rollback: Restore the previous backend image. The added database columns are nullable and do not invalidate existing scan history.

### 2026-09-28 09:30

Component: Backend / Scanner

Change: Replaced name-based scanner exclusions with current-request PID-tree classification to prevent the remote scanner shell and its descendants from being stored as risk processes.

Files:

- `backend/app/services/scanner.py`
- `README.md`

Reason: The prior scanner classified non-Teleport helper processes, including its own remote `sh`/`dash`, as application risks.

Apply: `docker compose up -d --build backend nginx`

Validation: Run a scan where only Teleport and the current scanner execution exist; expected status is SAFE with zero persisted risk processes.

Rollback: Restore the preceding backend image.

### 2026-09-28 09:45

Component: Backend / Scanner / Jobs

Change: Corrected an invalid shell branch terminator in the remote cgroup scanner script. Added exception logging around the asynchronous cgroup-job worker so an unexpected batch failure is recorded with its job ID instead of silently ending as `FAILED` with no node result.

Files:

- `backend/app/services/scanner.py`
- `backend/app/main.py`
- `README.md`

Reason: The invalid remote script caused `sh: Syntax error: "esac" unexpected`, which made single-node scans fail. Batch jobs used the same scanner release and previously did not retain an outer worker traceback for diagnosis.

Apply: `docker compose up -d --build backend nginx`

Validation: `sh -n` validates the rendered remote scanner script; scanner classification unit tests pass; backend healthcheck is healthy.

Rollback: Restore the immediately preceding backend image if required. Existing scan history is unchanged.

### 2026-09-28 10:00

Component: Backend / Scan Jobs / Service Config Jobs

Change: Fixed cross-thread reuse of expired SQLAlchemy session objects in background scan jobs. SSH workers now receive immutable session/node values and each completed node result is persisted through a fresh database session. Added bounded waves: `SCAN_BATCH_SIZE=10` and `SERVICE_CONFIG_BATCH_SIZE=10`. A 100-node request remains one job, scans/configures at most ten selected nodes per wave, persists progress per node, then starts the next wave. Service Config retains its separate `SERVICE_CONFIG_MAX_CONCURRENCY` limit within each ten-node wave.

Files:

- `backend/app/main.py`
- `backend/app/config.py`
- `.env`
- `.env.example`
- `README.md`

Reason: Batch jobs failed at 0% with `sqlalchemy.exc.PendingRollbackError` because an ORM session that had been committed/expired was accessed from SSH worker threads. Batching also protects the Teleport Proxy and backend when a large selection is submitted.

Apply: `docker compose up -d --build backend nginx`

Validation: A live read-only scan job for `K8S_Monitor2_10.129.11.175` through `.178` completed 4/4 SAFE. The scanner script syntax test and scanner classification unit tests pass.

Rollback: Restore the preceding backend image. Existing job and scan-result history is retained.

### 2026-09-28 10:20

Component: Backend / Scanner

Change: Encoded remote process command lines as Base64 before tab-delimited scanner output and decoded them only in the backend parser. Invalid scanner records now fail explicitly with `SCAN_PROTOCOL_INVALID` instead of producing a false `SAFE` result.

Files:

- `backend/app/services/scanner.py`
- `backend/tests/test_scanner_classification.py`
- `README.md`

Reason: A persistent multi-line `bash -c` worker in `teleport.service` contained tabs/newlines that shifted the old parser fields. Its `RISK` classification was not read and the node was incorrectly reported as SAFE.

Apply: `docker compose up -d --build backend nginx`

Validation: Scanner tests include a multi-line external bash worker and protocol-invalid input. Re-scan the affected node after deployment; the independent worker must be reported as WARNING.

Rollback: Restore the preceding backend image. Historical scan results are retained.

### 2026-09-28 10:35

Component: Backend / Scanner

Change: Corrected PPID parsing in the remote scanner. `/proc/<pid>/status` uses a tab after `PPid:` on the affected Linux host; the scanner now splits PPID values on all shell whitespace before producing a record.

Files:

- `backend/app/services/scanner.py`
- `README.md`

Reason: The former parser trimmed only a literal space. The retained tab added an empty output field, shifted the command/cgroup/classification columns, and caused a persistent external `bash -c` worker to be ignored or reported as SAFE.

Apply: `docker compose up -d --build backend nginx`

Validation: Re-scan `K8S_Monitor_Worker-02_10.129.8.8`; the independent long-running bash worker must persist as a WARNING result.

Rollback: Restore the preceding backend image. Historical scan results are retained.

### 2026-09-28 10:50

Component: Backend / Scanner / Security

Change: Classified Teleport daemon `start` processes before encoding command lines, added direct-ancestor recognition for only the current scanner's `teleport exec` wrapper, and redact sensitive command arguments (including `--token`) before a scan result is stored.

Files:

- `backend/app/services/scanner.py`
- `backend/tests/test_scanner_classification.py`
- `README.md`

Reason: The Base64 protocol change initially made core-process detection inspect the encoded string rather than the real command. It also exposed that command lines must be redacted before database persistence. Independent older Teleport sessions and their application processes remain RISK by design; only the current scanner execution tree is excluded.

Apply: `docker compose up -d --build backend nginx`

Validation: Re-scan the affected node and verify the long-running bash worker is WARNING, the Teleport daemon is not a risk row, current scan helper/wrapper processes are excluded, and no stored command contains the token value.

Rollback: Restore the preceding backend image. Historical scan results are retained.

### 2026-09-28 11:10

Component: Backend / Scanner / Classification

Change: Added `TELEPORT_SESSION` classification. The remote scanner now finds every live `/usr/local/bin/teleport exec` root in the cgroup snapshot and recursively excludes only its current descendants from risk persistence. Classification priority is `TELEPORT_CORE`, `SCAN_INTERNAL`, `TELEPORT_SESSION`, then `RISK`.

Files:

- `backend/app/services/scanner.py`
- `backend/tests/test_scanner_classification.py`
- `README.md`

Reason: Active interactive Teleport sessions (`teleport exec`, shells, `systemctl`, pagers, and their descendants) are normal transport activity, while detached processes with no currently active `teleport exec` ancestor must remain warnings.

Apply: `docker compose up -d --build backend nginx`

Validation: Re-scan `K8S_Monitor_Worker-02_10.129.8.8`; active session descendants must not be risk rows and the independent `teleport-killmode-test` bash process must remain a warning.

Rollback: Restore the preceding backend image. Historical scan results are retained.

### 2026-09-28 11:25

Component: Backend / Scanner / Reporting

Change: Persist only root processes of detached RISK trees. Descendants remain classified as risk in the scanner snapshot, but transient child helpers do not create duplicate warning rows or inflate Risk Process Count.

Files:

- `backend/app/services/scanner.py`
- `backend/tests/test_scanner_classification.py`
- `README.md`

Reason: A detached `bash -c teleport-killmode-test` worker legitimately spawns `sleep 5`. The operational report must identify the independent worker once, rather than report its recurring helper as a separate application risk.

Apply: `docker compose up -d --build backend nginx`

Validation: Re-scan `K8S_Monitor_Worker-02_10.129.8.8`; expected persisted risk result is only PID `2292468`.

Rollback: Restore the preceding backend image. Historical scan results are retained.
