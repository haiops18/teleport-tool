-- Backward-compatible: retains existing node statuses and permits progress states.
ALTER TABLE nodes
  MODIFY scan_status ENUM('QUEUED','SCANNING','SAFE','WARNING','ERROR','UNREACHABLE') NULL;
