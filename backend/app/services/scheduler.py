from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from ..database import SessionLocal
from ..models import Session
from .session_manager import remove
from .teleport import list_nodes
from datetime import datetime
def refresh_nodes(db, s):
    from ..main import upsert_nodes
    upsert_nodes(db,s,list_nodes(s.id,s.tsh_version)); db.commit()
def sweep():
    db=SessionLocal()
    try:
        now=datetime.utcnow()
        for s in db.scalars(select(Session).where(Session.status=='ACTIVE')).all():
            if s.expires_at and s.expires_at < now: s.status='EXPIRED'; remove(s.id)
        db.commit()
    finally: db.close()
def start():
    scheduler=BackgroundScheduler(timezone='UTC'); scheduler.add_job(sweep,'interval',minutes=10,id='session-cleanup',replace_existing=True); scheduler.start(); return scheduler
