from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    session_root: Path = Path('/data/sessions')
    export_root: Path = Path('/data/exports')
    session_ttl_hours: int = 12
    scan_concurrency: int = 10
    scan_batch_size: int = 10
    scan_max_nodes_per_request: int = 500
    ssh_timeout_seconds: int = 30
    scan_timeout_seconds: int = 60
    discovery_max_concurrency: int = 5
    discovery_batch_size: int = 10
    # Large requests are executed in bounded batches; this is a request cap, not
    # the number of SSH sessions started at once.
    discovery_max_nodes_per_request: int = 1800
    discovery_scan_timeout_seconds: int = 60
    service_config_max_concurrency: int = 5
    service_config_batch_size: int = 10
    service_config_max_nodes_per_request: int = 100
    teleport_restart_max_concurrency: int = 2
    teleport_restart_retry_interval: int = 5
    teleport_restart_max_wait: int = 120
    allowed_origins: str = 'http://localhost'
    admin_users: str = ''
    operator_users: str = ''
    default_role: str = 'VIEWER'
    tsh_binaries: dict = {'13.4':'/opt/tsh/13.4/tsh','14.4':'/opt/tsh/14.4/tsh','16.4':'/opt/tsh/16.4/tsh'}
settings = Settings()
