ALTER TABLE scan_results ADD COLUMN classification VARCHAR(32) NULL AFTER error_message, ADD COLUMN kill_mode VARCHAR(64) NULL AFTER classification;
