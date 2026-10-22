-- The migration runner guards ALTER statements against existing columns/indexes.
CREATE TABLE IF NOT EXISTS compute_discovery_jobs (
  id CHAR(36) PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  job_name VARCHAR(150) NOT NULL,
  created_by VARCHAR(255) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'QUEUED',
  total_nodes INT NOT NULL DEFAULT 0,
  completed_nodes INT NOT NULL DEFAULT 0,
  success_nodes INT NOT NULL DEFAULT 0,
  failed_nodes INT NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  CONSTRAINT fk_compute_discovery_jobs_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  INDEX ix_compute_discovery_jobs_session_created (session_id, created_at)
);
CREATE TABLE IF NOT EXISTS compute_discovery_results (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_id CHAR(36) NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  node_id BIGINT NOT NULL,
  hostname VARCHAR(255) NOT NULL,
  address VARCHAR(255), nic VARCHAR(64), compute VARCHAR(255), status VARCHAR(32) NOT NULL,
  detail TEXT, discovered_at DATETIME NOT NULL,
  CONSTRAINT fk_compute_discovery_results_job FOREIGN KEY (job_id) REFERENCES compute_discovery_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_compute_discovery_results_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  CONSTRAINT fk_compute_discovery_results_node FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
  INDEX ix_compute_discovery_results_job (job_id),
  INDEX ix_compute_discovery_results_session_node (session_id, node_id, id)
);
