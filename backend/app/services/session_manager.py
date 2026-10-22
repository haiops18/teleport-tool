import shutil, secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ..config import settings
def new_id(): return secrets.token_urlsafe(32)
def path(session_id: str) -> Path:
    p=settings.session_root/session_id; p.mkdir(parents=True, exist_ok=True, mode=0o700); return p
def expiry(): return datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=settings.session_ttl_hours)
def remove(session_id: str):
    p=settings.session_root/session_id
    if p.exists(): shutil.rmtree(p)
