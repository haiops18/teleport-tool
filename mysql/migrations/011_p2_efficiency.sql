CREATE TABLE IF NOT EXISTS saved_views (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255) NOT NULL, page VARCHAR(64) NOT NULL,
  name VARCHAR(100) NOT NULL, filters JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_saved_view_user_page_name (username, page, name), INDEX ix_saved_views_user_page (username, page)
);
CREATE TABLE IF NOT EXISTS export_jobs (
  id CHAR(36) PRIMARY KEY, session_id VARCHAR(64) NOT NULL, created_by VARCHAR(255) NOT NULL,
  export_type VARCHAR(32) NOT NULL, payload JSON NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
  filename VARCHAR(255), error_message TEXT, created_at DATETIME NOT NULL, started_at DATETIME, finished_at DATETIME,
  CONSTRAINT fk_export_jobs_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  INDEX ix_export_jobs_session_created (session_id, created_at)
);
CREATE TABLE IF NOT EXISTS scheduled_checks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, session_id VARCHAR(64) NOT NULL, created_by VARCHAR(255) NOT NULL,
  name VARCHAR(150) NOT NULL, operation VARCHAR(32) NOT NULL, node_ids JSON NOT NULL, interval_minutes INT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE, next_run_at DATETIME, last_run_at DATETIME, last_job_id VARCHAR(36),
  last_status VARCHAR(32), last_error TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  CONSTRAINT fk_scheduled_checks_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  INDEX ix_scheduled_checks_due (enabled, next_run_at), INDEX ix_scheduled_checks_session (session_id)
);
CREATE INDEX ix_nodes_session_hostname ON nodes (session_id, hostname);
CREATE INDEX ix_scan_results_job_node_status ON scan_results (scan_job_id, node_id, status);
CREATE INDEX ix_compute_discovery_results_session_node_time ON compute_discovery_results (session_id, node_id, discovered_at, id);
