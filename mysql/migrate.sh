#!/usr/bin/env bash
# Runs only additive/idempotent schema changes after MySQL is healthy.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib.sh
source "$ROOT_DIR/lib.sh"
detect_compose

mysql_exec() {
  compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"'
}
scalar() { printf '%s\n' "$1" | compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -Ns -uroot "$MYSQL_DATABASE"' | tr -d '[:space:]'; }
has_column() {
  [[ "$(scalar "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='$1' AND column_name='$2';")" == 1 ]]
}
has_index() {
  [[ "$(scalar "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='$1' AND index_name='$2';")" -ge 1 ]]
}
has_table() {
  [[ "$(scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$1';")" == 1 ]]
}
has_foreign_key() {
  [[ "$(scalar "SELECT COUNT(*) FROM information_schema.key_column_usage WHERE table_schema=DATABASE() AND table_name='$1' AND column_name='$2' AND referenced_table_name='$3';")" -ge 1 ]]
}

info 'Applying idempotent database migrations...'
mysql_exec <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(64) PRIMARY KEY,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
SQL

# 002: initial installs already have these indexes; older installs gain only missing ones.
has_index scan_results ix_scan_results_node_scanned || mysql_exec <<'SQL'
CREATE INDEX ix_scan_results_node_scanned ON scan_results (node_id, scanned_at);
SQL
has_index scan_jobs ix_scan_jobs_session_start || mysql_exec <<'SQL'
CREATE INDEX ix_scan_jobs_session_start ON scan_jobs (session_id, start_time);
SQL
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('002_report_indexes');" | mysql_exec

mysql_exec < "$ROOT_DIR/mysql/migrations/003_node_scan_progress_status.sql"
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('003_node_scan_progress_status');" | mysql_exec

mysql_exec < "$ROOT_DIR/mysql/migrations/004_service_config.sql"
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('004_service_config');" | mysql_exec

has_column scan_results classification || printf '%s\n' 'ALTER TABLE scan_results ADD COLUMN classification VARCHAR(32) NULL AFTER error_message;' | mysql_exec
has_column scan_results kill_mode || printf '%s\n' 'ALTER TABLE scan_results ADD COLUMN kill_mode VARCHAR(64) NULL AFTER classification;' | mysql_exec
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('005_killmode_scan_results');" | mysql_exec

has_column service_config_jobs job_name || printf '%s\n' 'ALTER TABLE service_config_jobs ADD COLUMN job_name VARCHAR(150) NULL AFTER created_by;' | mysql_exec
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('006_service_config_job_name');" | mysql_exec

# 007: Compute Discovery jobs/results. New installs get the complete schema from
# the SQL file; upgrades add only additive columns/indexes and retain history.
if ! has_table compute_discovery_jobs; then mysql_exec < "$ROOT_DIR/mysql/migrations/007_compute_discovery_jobs.sql"; fi
has_column compute_discovery_jobs job_name || printf '%s\n' "ALTER TABLE compute_discovery_jobs ADD COLUMN job_name VARCHAR(150) NOT NULL DEFAULT 'Discovery Scan - migrated' AFTER session_id;" | mysql_exec
has_column compute_discovery_jobs created_by || printf '%s\n' "ALTER TABLE compute_discovery_jobs ADD COLUMN created_by VARCHAR(255) NOT NULL DEFAULT 'unknown' AFTER job_name;" | mysql_exec
has_column compute_discovery_jobs success_nodes || printf '%s\n' 'ALTER TABLE compute_discovery_jobs ADD COLUMN success_nodes INT NOT NULL DEFAULT 0 AFTER completed_nodes;' | mysql_exec
has_column compute_discovery_jobs failed_nodes || printf '%s\n' 'ALTER TABLE compute_discovery_jobs ADD COLUMN failed_nodes INT NOT NULL DEFAULT 0 AFTER success_nodes;' | mysql_exec
has_column compute_discovery_jobs error_message || printf '%s\n' 'ALTER TABLE compute_discovery_jobs ADD COLUMN error_message TEXT NULL AFTER failed_nodes;' | mysql_exec
has_index compute_discovery_jobs ix_compute_discovery_jobs_session_created || printf '%s\n' 'CREATE INDEX ix_compute_discovery_jobs_session_created ON compute_discovery_jobs (session_id, created_at);' | mysql_exec
if ! has_table compute_discovery_results; then mysql_exec < "$ROOT_DIR/mysql/migrations/007_compute_discovery_jobs.sql"; fi
has_column compute_discovery_results job_id || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD COLUMN job_id CHAR(36) NULL AFTER id;' | mysql_exec
# Preserve legacy rows which predate discovery jobs: attach each to a deterministic
# synthetic job before enforcing the durable job/result foreign key.
mysql_exec <<'SQL'
INSERT IGNORE INTO compute_discovery_jobs (id,session_id,job_name,created_by,status,total_nodes,completed_nodes,success_nodes,failed_nodes,created_at,started_at,finished_at)
SELECT CONCAT('legacy-',LEFT(MD5(session_id),29)), session_id, 'Legacy Discovery - migrated', 'migration', 'COMPLETED', 0, 0, 0, 0, NOW(), NOW(), NOW()
FROM compute_discovery_results WHERE job_id IS NULL GROUP BY session_id;
UPDATE compute_discovery_results
SET job_id=CONCAT('legacy-',LEFT(MD5(session_id),29))
WHERE job_id IS NULL;
SQL
if ! has_foreign_key compute_discovery_results job_id compute_discovery_jobs; then
  printf '%s\n' 'ALTER TABLE compute_discovery_results MODIFY COLUMN job_id CHAR(36) NOT NULL;' | mysql_exec
fi
has_index compute_discovery_results ix_compute_discovery_results_job || printf '%s\n' 'CREATE INDEX ix_compute_discovery_results_job ON compute_discovery_results (job_id);' | mysql_exec
has_index compute_discovery_results ix_compute_discovery_results_session_node || printf '%s\n' 'CREATE INDEX ix_compute_discovery_results_session_node ON compute_discovery_results (session_id, node_id, id);' | mysql_exec
has_foreign_key compute_discovery_results job_id compute_discovery_jobs || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD CONSTRAINT fk_compute_discovery_results_job FOREIGN KEY (job_id) REFERENCES compute_discovery_jobs(id) ON DELETE CASCADE;' | mysql_exec
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('007_compute_discovery_jobs');" | mysql_exec
# 008: reason metadata is additive; legacy NOT_DETECTED rows are preserved and
# presented as LEGACY_UNKNOWN by the report layer.
has_column compute_discovery_results reason_code || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD COLUMN reason_code VARCHAR(64) NULL AFTER status;' | mysql_exec
has_column compute_discovery_results reason_message || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD COLUMN reason_message TEXT NULL AFTER reason_code;' | mysql_exec
has_index compute_discovery_results ix_compute_discovery_results_status_reason || printf '%s\n' 'CREATE INDEX ix_compute_discovery_results_status_reason ON compute_discovery_results (session_id, status, reason_code, discovered_at);' | mysql_exec
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('008_compute_discovery_reasons');" | mysql_exec
has_column compute_discovery_results failed_stage || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD COLUMN failed_stage VARCHAR(64) NULL AFTER status;' | mysql_exec
has_column compute_discovery_results command_exit_code || printf '%s\n' 'ALTER TABLE compute_discovery_results ADD COLUMN command_exit_code INT NULL AFTER reason_message;' | mysql_exec
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('009_compute_discovery_diagnostics');" | mysql_exec
has_column sessions role || printf '%s\n' "ALTER TABLE sessions ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'VIEWER' AFTER status;" | mysql_exec
has_table audit_logs || mysql_exec <<'SQL'
CREATE TABLE audit_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME NOT NULL, username VARCHAR(255) NOT NULL, role VARCHAR(16) NOT NULL, action VARCHAR(64) NOT NULL, target_type VARCHAR(64), target_count INT NOT NULL DEFAULT 0, job_id VARCHAR(36), result VARCHAR(32) NOT NULL, source_ip VARCHAR(64), details TEXT, INDEX ix_audit_timestamp (timestamp), INDEX ix_audit_username (username));
SQL
printf '%s\n' "INSERT IGNORE INTO schema_migrations(version) VALUES ('010_auth_rbac_audit');" | mysql_exec
ok 'Database schema is current.'
