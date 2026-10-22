-- Apply once to existing deployments. These indexes support report filters and latest-scan aggregation.
CREATE INDEX ix_scan_results_node_scanned ON scan_results (node_id, scanned_at);
CREATE INDEX ix_scan_jobs_session_start ON scan_jobs (session_id, start_time);
