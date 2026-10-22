import logging, threading, uuid
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI, Depends, Header, HTTPException, BackgroundTasks, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from sqlalchemy import String, and_, cast, func, or_, select, update, delete
from sqlalchemy.orm import Session as Db
from .config import settings
from .database import Base, engine, db_session, SessionLocal
from .models import Session,Node,ScanJob,ScanResult,ServiceConfigJob,ServiceConfigResult,ComputeDiscoveryJob,ComputeDiscoveryResult,AuditLog
from .schemas.api import LoginRequest,ScanRequest,ComputeDiscoveryRequest,ServiceConfigRequest,ReportExportRequest,ReportRemoveRequest
from .services import teleport
from .services.session_manager import new_id,path,expiry,remove
from .services.scanner import scan_node
from .services.compute_discovery import discover as discover_compute
from .services.excel import export
from .services import report_service, compute_report_service
from .services import service_config
from .services.scheduler import start
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger(__name__)
scheduler=None
audit_source_ip=ContextVar('audit_source_ip',default=None)
@asynccontextmanager
async def lifespan(app):
    global scheduler; Base.metadata.create_all(engine); settings.session_root.mkdir(parents=True,exist_ok=True); settings.export_root.mkdir(parents=True,exist_ok=True)
    # Threads are process-local. A process restart cannot safely resume their SSH work.
    db=SessionLocal()
    try:
        stale=db.scalars(select(ComputeDiscoveryJob).where(ComputeDiscoveryJob.status.in_(['QUEUED','RUNNING']))).all()
        for job in stale:
            job.status='FAILED'; job.error_message='INTERRUPTED_BY_BACKEND_RESTART'; job.finished_at=datetime.utcnow()
        stale_scans=db.scalars(select(ScanJob).where(ScanJob.status.in_(['PENDING','QUEUED','RUNNING']))).all()
        for job in stale_scans:
            job.status='FAILED'; job.end_time=datetime.utcnow()
        stale_service=db.scalars(select(ServiceConfigJob).where(ServiceConfigJob.status.in_(['QUEUED','RUNNING']))).all()
        for job in stale_service:
            job.status='FAILED'; job.finished_at=datetime.utcnow()
        if stale or stale_scans or stale_service:
            db.commit(); log.warning('STALE_JOBS_FINALIZED discovery=%s scan=%s service=%s',len(stale),len(stale_scans),len(stale_service))
    finally: db.close()
    scheduler=start(); yield
    scheduler.shutdown()
app=FastAPI(title='Teleport Cgroup Scanner',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.allowed_origins.split(','),allow_credentials=False,allow_methods=['*'],allow_headers=['*'])
@app.middleware('http')
async def access_log(request, call_next):
    request_id=request.headers.get('X-Request-ID',str(uuid.uuid4())); started=datetime.utcnow()
    token=audit_source_ip.set(request.client.host if request.client else None)
    try: response=await call_next(request)
    finally: audit_source_ip.reset(token)
    log.info('request_id=%s session_id=%s node=- action=%s duration_ms=%d status=%d',request_id,request.headers.get('X-Session-Id','-'),request.method+' '+request.url.path,int((datetime.utcnow()-started).total_seconds()*1000),response.status_code)
    response.headers['X-Request-ID']=request_id; return response
def active(x_session_id: str|None=Header(None,alias='X-Session-Id'), db:Db=Depends(db_session)):
    if not x_session_id: raise HTTPException(401,'AUTHENTICATION_REQUIRED')
    s=db.get(Session,x_session_id)
    if not s or s.status!='ACTIVE' or (s.expires_at and s.expires_at<datetime.utcnow()): raise HTTPException(401,'SESSION_EXPIRED')
    return s
def user_role(username):
    name=username.strip().lower()
    if name in {x.strip().lower() for x in settings.admin_users.split(',') if x.strip()}: return 'ADMIN'
    if name in {x.strip().lower() for x in settings.operator_users.split(',') if x.strip()}: return 'OPERATOR'
    return settings.default_role.upper()
def require(s,*roles):
    if s.role not in roles: raise HTTPException(403,'INSUFFICIENT_ROLE')
def audit(db,s,action,target_type=None,target_count=0,job_id=None,result='SUCCESS',details=None):
    db.add(AuditLog(timestamp=datetime.utcnow(),username=s.username,role=s.role,action=action,target_type=target_type,target_count=target_count,job_id=job_id,result=result,source_ip=audit_source_ip.get(),details=details)); db.commit()
def node_status(value):
    """Expose one status vocabulary to the UI without changing scan history."""
    if value == 'UNREACHABLE': return 'ERROR'
    return value if value in {'QUEUED','SCANNING','SAFE','WARNING','ERROR'} else 'UNKNOWN'
def serialize_node(n, discovery=None):
    result={k:getattr(n,k) for k in ('id','hostname','node_id','address','cluster','labels','teleport_version','last_seen','last_refresh','scan_status','last_scan')}
    result['status']=node_status(n.scan_status)
    if discovery:
        result['latest_compute']=discovery.compute; result['discovery_status']=discovery.status; result['discovery_reason_code']=discovery.reason_code; result['discovery_reason_message']=discovery.reason_message; result['last_discovery']=discovery.discovered_at
    return result
def upsert_nodes(db,s,items):
    now=datetime.utcnow()
    for item in items:
        hostname=item.get('hostname') or item.get('name') or item.get('Hostname')
        if not hostname: continue
        n=db.scalar(select(Node).where(Node.session_id==s.id,Node.hostname==hostname))
        if not n: n=Node(session_id=s.id,hostname=hostname); db.add(n)
        n.node_id=str(item.get('id') or item.get('node_id') or '') or None; n.address=item.get('addr') or item.get('address') or item.get('hostname')
        n.cluster=item.get('cluster_name') or item.get('cluster') or s.cluster; n.labels=item.get('labels') or {}; n.teleport_version=item.get('version') or item.get('teleport_version'); n.last_seen=now; n.last_refresh=now
    return len(items)
def refresh_session_nodes(db,s):
    count=upsert_nodes(db,s,teleport.list_nodes(s.id,s.tsh_version)); db.commit(); return count
@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/auth/login')
def login(body:LoginRequest,db:Db=Depends(db_session)):
    sid=new_id(); path(sid)
    try: teleport.login(sid,body.proxy,body.tsh_version,body.username,body.password,body.otp); info=teleport.status(sid,body.tsh_version)
    except Exception:
        remove(sid); raise
    s=Session(id=sid,username=body.username,proxy=body.proxy,tsh_version=body.tsh_version,cluster=info.get('Cluster'),logged_in_at=datetime.utcnow(),expires_at=expiry(),status='ACTIVE',role=user_role(body.username)); db.add(s); db.commit(); audit(db,s,'LOGIN')
    try: node_count=refresh_session_nodes(db,s); node_refresh_error=None
    except Exception as exc: db.rollback(); node_count=0; node_refresh_error=getattr(exc,'detail','NODE_LIST_FAILED')
    return {'session_id':sid,'username':s.username,'role':s.role,'proxy':s.proxy,'tsh_version':s.tsh_version,'cluster':s.cluster,'valid_until':s.expires_at,'status':'ACTIVE','node_count':node_count,'node_refresh_error':node_refresh_error}
@app.post('/auth/logout')
def logout(s:Session=Depends(active),db:Db=Depends(db_session)):
    audit(db,s,'LOGOUT'); s.status='LOGGED_OUT'; db.commit(); remove(s.id); return {'status':'LOGGED_OUT'}
@app.get('/auth/status')
def auth_status(s:Session=Depends(active)):
    # Application authorization is based on the persisted, server-validated session.
    # A transient Teleport status error must not turn an otherwise active app session
    # into a false logout in the browser.
    try: info=teleport.status(s.id,s.tsh_version)
    except Exception: info={}
    return {'session_id':s.id,'username':s.username,'role':s.role,'proxy':s.proxy,'tsh_version':s.tsh_version,'cluster':info.get('Cluster',s.cluster),'valid_until':info.get('Valid until',s.expires_at),'roles':info.get('Roles'),'status':'ACTIVE'}
@app.get('/nodes')
def nodes(q:str='',search:str='',status:str='',discovery_status:str='',offset:int|None=None,limit:int|None=None,page:int|None=None,page_size:int|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    """Server-side node search. q/offset/limit remain for older clients."""
    term=(search or q).strip()
    effective_limit=min(page_size or limit or 50,200)
    effective_offset=((max(page or 1,1)-1)*effective_limit) if page is not None else max(offset or 0,0)
    latest_ids=select(func.max(ComputeDiscoveryResult.id).label('id')).where(ComputeDiscoveryResult.session_id==s.id).group_by(ComputeDiscoveryResult.node_id).subquery()
    stmt=select(Node,ComputeDiscoveryResult).outerjoin(ComputeDiscoveryResult,and_(ComputeDiscoveryResult.id.in_(select(latest_ids.c.id)),ComputeDiscoveryResult.node_id==Node.id)).where(Node.session_id==s.id)
    if term:
        like=f'%{term}%'
        stmt=stmt.where(or_(Node.hostname.ilike(like),Node.node_id.ilike(like),Node.address.ilike(like),cast(Node.labels,String).ilike(like),ComputeDiscoveryResult.compute.ilike(like),ComputeDiscoveryResult.status.ilike(like),ComputeDiscoveryResult.reason_code.ilike(like)))
    if status:
        wanted=status.upper()
        if wanted=='ERROR': stmt=stmt.where(Node.scan_status.in_(['ERROR','UNREACHABLE']))
        elif wanted=='UNKNOWN': stmt=stmt.where(or_(Node.scan_status.is_(None),Node.scan_status.not_in(['QUEUED','SCANNING','SAFE','WARNING','ERROR','UNREACHABLE'])))
        else: stmt=stmt.where(Node.scan_status==wanted)
    if discovery_status:
        if discovery_status=='NOT_SCANNED': stmt=stmt.where(ComputeDiscoveryResult.id.is_(None))
        else: stmt=stmt.where(ComputeDiscoveryResult.status==discovery_status)
    count=db.scalar(select(func.count()).select_from(stmt.subquery()))
    data=db.execute(stmt.order_by(Node.hostname).offset(effective_offset).limit(effective_limit)).all()
    last_refresh=db.scalar(select(func.max(Node.last_refresh)).where(Node.session_id==s.id))
    return {'items':[serialize_node(node,discovery) for node,discovery in data],'total':count,'page':(effective_offset//effective_limit)+1,'page_size':effective_limit,'last_refresh':last_refresh,'next_refresh_seconds':300}
@app.post('/nodes/refresh')
def refresh(s:Session=Depends(active),db:Db=Depends(db_session)):
    return {'status':'ok','count':refresh_session_nodes(db,s)}
def _scan_job_cancelled(job_id):
    db=SessionLocal()
    try:
        job=db.get(ScanJob,job_id)
        return not job or job.status=='CANCELLED'
    finally: db.close()

def _set_batch_status(job_id, node_ids, status):
    """Persist the current batch state without sharing an ORM session with SSH workers."""
    db=SessionLocal()
    try:
        job=db.get(ScanJob,job_id)
        if not job or job.status=='CANCELLED': return False
        db.execute(update(Node).where(Node.id.in_(node_ids),Node.session_id==job.session_id).values(scan_status=status))
        db.commit()
        return True
    except Exception:
        db.rollback()
        log.exception('scan_batch_status_failed job_id=%s',job_id)
        raise
    finally: db.close()

def _persist_scan_completion(job_id, target, status, rows):
    """Each completion gets a fresh DB session; SSH work never owns an ORM session."""
    db=SessionLocal()
    try:
        job=db.get(ScanJob,job_id)
        node=db.get(Node,target.id)
        if not job or not node or job.status=='CANCELLED': return False
        node.scan_status=status; node.last_scan=datetime.utcnow()
        for value in rows:
            db.add(ScanResult(scan_job_id=job.id,node_id=node.id,hostname=node.hostname,address=node.address,status=value['status'],scanned_at=datetime.utcnow(),**{k:v for k,v in value.items() if k!='status'}))
        job.completed_nodes+=1
        if status=='SAFE': job.safe_nodes+=1
        elif status=='WARNING': job.warning_nodes+=1
        elif status=='UNREACHABLE': job.unreachable_nodes+=1
        else: job.error_nodes+=1
        db.commit()
        return True
    except Exception:
        db.rollback()
        log.exception('scan_result_persist_failed job_id=%s node_id=%s',job_id,target.id)
        raise
    finally: db.close()

def execute_job(job_id):
    """Run a durable scan job in bounded waves, defaulting to ten nodes per wave."""
    try:
        db=SessionLocal()
        try:
            job=db.get(ScanJob,job_id)
            if not job or job.status=='CANCELLED': return
            session=db.get(Session,job.session_id)
            node_ids=_job_nodes.pop(job_id,[])
            selected=db.scalars(select(Node).where(Node.session_id==session.id,Node.id.in_(node_ids))).all()
            # Do not hand SQLAlchemy objects to threads: commit expires attributes and
            # cross-thread lazy loading corrupts the parent transaction.
            ssh_session=SimpleNamespace(id=session.id,tsh_version=session.tsh_version)
            targets=[SimpleNamespace(id=node.id,hostname=node.hostname) for node in selected]
            job.status='RUNNING'; db.commit()
        finally:
            db.close()

        batch_size=max(1,min(settings.scan_batch_size,settings.scan_concurrency))
        for start_index in range(0,len(targets),batch_size):
            if _scan_job_cancelled(job_id): return
            batch=targets[start_index:start_index+batch_size]
            if not _set_batch_status(job_id,[target.id for target in batch],'SCANNING'): return
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures={pool.submit(scan_node,ssh_session,target):target for target in batch}
                for future in as_completed(futures):
                    target=futures[future]
                    if _scan_job_cancelled(job_id):
                        for pending in futures: pending.cancel()
                        return
                    try: status,rows=future.result()
                    except Exception:
                        log.exception('scan_node_failed job_id=%s node_id=%s',job_id,target.id)
                        status,rows='ERROR',[{'status':'ERROR','error_message':'SCAN_FAILED'}]
                    _persist_scan_completion(job_id,target,status,rows)

        db=SessionLocal()
        try:
            job=db.get(ScanJob,job_id)
            if job and job.status!='CANCELLED': job.status='COMPLETED'; job.end_time=datetime.utcnow(); db.commit()
        finally: db.close()
    except Exception:
        log.exception('scan_job_failed job_id=%s',job_id)
        db=SessionLocal()
        try:
            job=db.get(ScanJob,job_id)
            if job and job.status!='CANCELLED': job.status='FAILED'; job.end_time=datetime.utcnow(); db.commit()
        finally: db.close()
_job_nodes={}
def create_job(ids,s,db):
    for node in db.scalars(select(Node).where(Node.session_id==s.id,Node.id.in_(ids))).all(): node.scan_status='QUEUED'
    job=ScanJob(id=str(uuid.uuid4()),session_id=s.id,start_time=datetime.utcnow(),total_nodes=len(ids),created_by=s.username); db.add(job); db.commit(); _job_nodes[job.id]=ids; threading.Thread(target=execute_job,args=(job.id,),daemon=True).start(); return {'job_id':job.id,'status':'QUEUED','total_nodes':len(ids),'node_ids':ids}
@app.post('/nodes/{node_id}/scan')
def scan_one(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'OPERATOR','ADMIN')
    if not db.scalar(select(Node.id).where(Node.id==node_id,Node.session_id==s.id)): raise HTTPException(404,'NODE_NOT_FOUND')
    value=create_job([node_id],s,db); audit(db,s,'PROCESS_SCAN_CREATE','NODE',1,value['job_id']); return value
@app.post('/scan')
def scan(body:ScanRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'OPERATOR','ADMIN')
    ids=list(dict.fromkeys(body.node_ids))
    if not ids: raise HTTPException(400,'NODE_IDS_REQUIRED')
    if len(ids)>settings.scan_max_nodes_per_request: raise HTTPException(400,'TOO_MANY_NODES')
    found=set(db.scalars(select(Node.id).where(Node.session_id==s.id,Node.id.in_(ids))).all())
    if found != set(ids): raise HTTPException(404,'NODE_NOT_FOUND')
    value=create_job(ids,s,db); audit(db,s,'PROCESS_SCAN_CREATE','NODE',len(ids),value['job_id']); return value
_compute_nodes={}
def _compute_job_payload(job):
    values={key:getattr(job,key) for key in ('id','job_name','created_by','status','total_nodes','completed_nodes','success_nodes','failed_nodes','created_at','started_at','finished_at','error_message')}
    values.update({'job_id':job.id,'job_type':'COMPUTE DISCOVERY','total':job.total_nodes,'completed':job.completed_nodes,'success':job.success_nodes,'error':job.failed_nodes})
    values['progress_percent']=round((job.completed_nodes/job.total_nodes)*100,1) if job.total_nodes else 0
    return values

def _persist_compute_completion(job_id, target, row):
    db=SessionLocal()
    try:
        job=db.get(ComputeDiscoveryJob,job_id)
        if not job or job.status not in ('QUEUED','RUNNING'): return
        db.add(ComputeDiscoveryResult(job_id=job.id,session_id=job.session_id,node_id=target.id,hostname=target.hostname,address=target.address,nic=row.get('nic'),compute=row.get('compute'),status=row['status'],failed_stage=row.get('failed_stage'),reason_code=row.get('reason_code'),reason_message=row.get('reason_message'),command_exit_code=row.get('command_exit_code'),detail=row.get('detail'),discovered_at=datetime.utcnow()))
        job.completed_nodes+=1
        if row['status']=='DETECTED': job.success_nodes+=1
        elif row['status'] in ('ERROR','UNREACHABLE'): job.failed_nodes+=1
        db.commit()
        log.info('DISCOVERY_NODE_%s job_id=%s node_id=%s', row['status'],job_id,target.id)
    except Exception:
        db.rollback(); log.exception('discovery_result_persist_failed job_id=%s node_id=%s',job_id,target.id)
        raise
    finally: db.close()

def _execute_compute_job(job_id):
    try:
        db=SessionLocal()
        try:
            job=db.get(ComputeDiscoveryJob,job_id)
            if not job: return
            session=db.get(Session,job.session_id); ids=_compute_nodes.pop(job_id,[])
            selected=db.scalars(select(Node).where(Node.session_id==job.session_id,Node.id.in_(ids))).all()
            if not session or not selected: raise RuntimeError('DISCOVERY_JOB_HAS_NO_TARGETS')
            targets=[SimpleNamespace(id=n.id,hostname=n.hostname,address=n.address) for n in selected]
            ssh=SimpleNamespace(id=session.id,tsh_version=session.tsh_version)
            job.status='RUNNING'; job.started_at=datetime.utcnow(); db.commit()
            log.info('DISCOVERY_JOB_STARTED job_id=%s total=%s',job_id,len(targets))
        finally: db.close()
        batch_size=max(1,min(settings.discovery_batch_size,settings.discovery_max_concurrency))
        for start_index in range(0,len(targets),batch_size):
            batch=targets[start_index:start_index+batch_size]
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures={pool.submit(discover_compute,ssh,target):target for target in batch}
                for future in as_completed(futures):
                    target=futures[future]
                    try: row=future.result()
                    except Exception as exc:
                        row={'node_id':target.id,'hostname':target.hostname,'address':target.address,'nic':None,'compute':None,'status':'ERROR','failed_stage':'INTERNAL','reason_code':'INTERNAL_ERROR','reason_message':'Discovery worker raised an unexpected exception.','detail':str(exc)[:500]}
                    _persist_compute_completion(job_id,target,row)
        db=SessionLocal()
        try:
            job=db.get(ComputeDiscoveryJob,job_id)
            if job:
                job.status='COMPLETED'; job.finished_at=datetime.utcnow(); db.commit()
                log.info('DISCOVERY_JOB_COMPLETED job_id=%s completed=%s',job_id,job.completed_nodes)
        finally: db.close()
    except Exception as exc:
        log.exception('compute_discovery_job_failed job_id=%s',job_id)
        db=SessionLocal()
        try:
            job=db.get(ComputeDiscoveryJob,job_id)
            if job: job.status='FAILED'; job.error_message=str(exc)[:500]; job.finished_at=datetime.utcnow(); db.commit()
        finally: db.close()

def create_compute_job(body,s,db):
    ids=list(dict.fromkeys(body.node_ids))
    if len(ids)>settings.discovery_max_nodes_per_request: raise HTTPException(400,'TOO_MANY_NODES')
    nodes=db.scalars(select(Node).where(Node.session_id==s.id,Node.id.in_(ids))).all()
    if len(nodes)!=len(ids): raise HTTPException(404,'NODE_NOT_FOUND')
    now=datetime.utcnow(); name=body.job_name or f'Discovery Scan - {now.strftime("%Y-%m-%d %H:%M:%S")}'
    job=ComputeDiscoveryJob(id=str(uuid.uuid4()),session_id=s.id,job_name=name,created_by=s.username,status='QUEUED',total_nodes=len(ids),created_at=now)
    db.add(job); db.commit(); _compute_nodes[job.id]=ids
    threading.Thread(target=_execute_compute_job,args=(job.id,),daemon=True).start()
    log.info('DISCOVERY_JOB_CREATED job_id=%s total=%s',job.id,len(ids))
    return _compute_job_payload(job)

@app.post('/compute-discovery/jobs')
def create_compute_discovery_job(body:ComputeDiscoveryRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'OPERATOR','ADMIN'); value=create_compute_job(body,s,db); audit(db,s,'DISCOVERY_SCAN_CREATE','NODE',len(body.node_ids),value['job_id']); return value

@app.post('/compute-discovery')
def compute_discovery_legacy(body:ComputeDiscoveryRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    """Compatibility route; callers now receive a queued background job immediately."""
    require(s,'OPERATOR','ADMIN'); value=create_compute_job(body,s,db); audit(db,s,'DISCOVERY_SCAN_CREATE','NODE',len(body.node_ids),value['job_id']); return value

@app.get('/compute-discovery/jobs')
def compute_jobs(s:Session=Depends(active),db:Db=Depends(db_session)):
    return {'items':[_compute_job_payload(j) for j in db.scalars(select(ComputeDiscoveryJob).where(ComputeDiscoveryJob.session_id==s.id).order_by(ComputeDiscoveryJob.created_at.desc())).all()]}

@app.get('/compute-discovery/jobs/{job_id}')
def compute_job(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ComputeDiscoveryJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'COMPUTE_JOB_NOT_FOUND')
    value=_compute_job_payload(j); value['nodes']=compute_report_service.job_results(db,s.id,job_id)
    return value

@app.get('/compute-discovery/jobs/{job_id}/results')
def compute_results(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    if not db.scalar(select(ComputeDiscoveryJob.id).where(ComputeDiscoveryJob.id==job_id,ComputeDiscoveryJob.session_id==s.id)): raise HTTPException(404,'COMPUTE_JOB_NOT_FOUND')
    return {'items':compute_report_service.job_results(db,s.id,job_id)}

@app.get('/compute-discovery/history')
def compute_history(s:Session=Depends(active),db:Db=Depends(db_session)):
    return compute_jobs(s,db)

@app.get('/compute-discovery/report')
def compute_discovery_report(s:Session=Depends(active),db:Db=Depends(db_session)):
    return compute_report_service.summary(db,s.id)

@app.get('/compute-discovery/report/groups')
def compute_report_groups(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),search:str|None=None,status:str|None=None,job_id:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    return compute_report_service.groups(db,s.id,page,page_size,search,status,job_id)

@app.get('/compute-discovery/report/nodes')
def compute_report_nodes(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),search:str|None=None,status:str|None=None,job_id:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    return compute_report_service.nodes(db,s.id,page,page_size,search,status,job_id)

@app.get('/compute-discovery/report/history')
def compute_report_history(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),search:str|None=None,status:str|None=None,job_id:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    return compute_report_service.history(db,s.id,page,page_size,search,status,job_id)

@app.get('/compute-discovery/export')
def compute_report_export(search:str|None=None,status:str|None=None,job_id:str|None=None,node_ids:list[int]|None=Query(None),s:Session=Depends(active),db:Db=Depends(db_session)):
    output=compute_report_service.export_discovery(db,s,search,status,job_id,node_ids); audit(db,s,'REPORT_EXPORT','COMPUTE_DISCOVERY',len(node_ids or []),job_id)
    return FileResponse(output,filename=output.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
@app.get('/scan/{job_id}')
def scan_job(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ScanJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'JOB_NOT_FOUND')
    result={k:getattr(j,k) for k in ('id','status','start_time','end_time','total_nodes','completed_nodes','safe_nodes','warning_nodes','error_nodes','unreachable_nodes')}
    result['progress_percent']=round((j.completed_nodes/j.total_nodes)*100,1) if j.total_nodes else 0
    return result
@app.get('/scan/{job_id}/results')
def results(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ScanJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'JOB_NOT_FOUND')
    return [ {c.name:getattr(x,c.name) for c in ScanResult.__table__.columns} for x in db.scalars(select(ScanResult).where(ScanResult.scan_job_id==job_id)).all()]
@app.post('/scan/{job_id}/cancel')
def cancel(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ScanJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'JOB_NOT_FOUND')
    if j.status in ('PENDING','QUEUED','RUNNING'): j.status='CANCELLED'; j.end_time=datetime.utcnow(); db.commit()
    return {'id':j.id,'status':j.status}
@app.post('/export/{job_id}')
def make_export(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ScanJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'JOB_NOT_FOUND')
    p=export(j,s,db.scalars(select(ScanResult).where(ScanResult.scan_job_id==job_id)).all()); return {'filename':p.name,'download_url':f'/api/export/{job_id}/download'}
@app.get('/export/{job_id}/download')
def download(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    matches=sorted(settings.export_root.glob('teleport_cgroup_scan_*.xlsx'),key=lambda x:x.stat().st_mtime,reverse=True)
    j=db.get(ScanJob,job_id)
    if not j or j.session_id!=s.id or not matches: raise HTTPException(404,'EXPORT_NOT_FOUND')
    return FileResponse(matches[0],filename=matches[0].name)
@app.get('/history')
def history(s:Session=Depends(active),db:Db=Depends(db_session)):
    values=[]
    for j in db.scalars(select(ScanJob).where(ScanJob.session_id==s.id).order_by(ScanJob.start_time.desc())).all():
        value={k:getattr(j,k) for k in ('id','start_time','end_time','total_nodes','completed_nodes','safe_nodes','warning_nodes','error_nodes','unreachable_nodes','status','created_by')}
        value['progress_percent']=round((j.completed_nodes/j.total_nodes)*100,1) if j.total_nodes else 0
        values.append(value)
    return values
@app.get('/history/{job_id}')
def history_one(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)): return scan_job(job_id,s,db)
@app.get('/reports/summary')
def report_summary(period:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    log.info('report_summary_requested session_id=%s',s.id); return report_service.summary(db,s.id,period)
@app.get('/reports/hosts')
def report_hosts(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),status:str|None=None,search:str|None=Query(None,max_length=255),period:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    if status and status not in {'SAFE','WARNING','ERROR','UNKNOWN'}: raise HTTPException(400,'INVALID_STATUS')
    log.info('report_hosts_requested session_id=%s',s.id); return report_service.hosts(db,s.id,page,page_size,status,search,period)
@app.get('/reports/hosts/{node_id}')
def report_host(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)):
    value=report_service.host_detail(db,s.id,node_id)
    if not value: raise HTTPException(404,'REPORT_HOST_NOT_FOUND')
    log.info('report_host_detail_requested session_id=%s node=%s',s.id,node_id); return value
@app.get('/reports/hosts/{node_id}/scans')
def report_host_scans(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)):
    value=report_service.host_detail(db,s.id,node_id)
    if not value: raise HTTPException(404,'REPORT_HOST_NOT_FOUND')
    return value['history']
@app.get('/reports/scans/{scan_id}')
def report_scan(scan_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    value=report_service.scan_detail(db,s.id,scan_id)
    if not value: raise HTTPException(404,'REPORT_SCAN_NOT_FOUND')
    return value
@app.get('/reports/export')
def report_export(search:str|None=None,status:str|None=None,s:Session=Depends(active),db:Db=Depends(db_session)):
    log.info('report_export_started session_id=%s',s.id); path=report_service.export_report(db,s.id,search=search,status=status); audit(db,s,'REPORT_EXPORT','PROCESS_SCAN'); log.info('report_export_completed session_id=%s',s.id); return FileResponse(path,filename=path.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
@app.post('/reports/export')
def report_export_selected(body:ReportExportRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    ids=list(dict.fromkeys(body.node_ids)); found=set(db.scalars(select(Node.id).where(Node.session_id==s.id,Node.id.in_(ids))).all())
    if found!=set(ids): raise HTTPException(404,'NODE_NOT_FOUND')
    path=report_service.export_report(db,s.id,node_ids=ids)
    return FileResponse(path,filename=path.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
def _remove_report_nodes(ids,s,db):
    require(s,'ADMIN')
    ids=list(dict.fromkeys(ids)); found=set(db.scalars(select(Node.id).where(Node.session_id==s.id,Node.id.in_(ids))).all())
    if found!=set(ids): raise HTTPException(404,'NODE_NOT_FOUND')
    active=set(db.scalars(select(Node.id).where(Node.id.in_(ids),Node.scan_status.in_(['QUEUED','SCANNING']))).all())
    if active: raise HTTPException(409,'REPORT_REMOVE_BLOCKED_ACTIVE_SCAN')
    db.execute(delete(ScanResult).where(ScanResult.node_id.in_(ids),ScanResult.scan_job_id.in_(select(ScanJob.id).where(ScanJob.session_id==s.id))))
    db.commit(); audit(db,s,'REPORT_REMOVE','NODE',len(ids)); return {'requested':len(ids),'removed':len(ids),'failed':0,'results':[{'node_id':x,'status':'REMOVED'} for x in ids]}
@app.delete('/reports/nodes/{node_id}')
def report_remove_one(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)): return _remove_report_nodes([node_id],s,db)
@app.post('/reports/remove')
def report_remove(body:ReportRemoveRequest,s:Session=Depends(active),db:Db=Depends(db_session)): return _remove_report_nodes(body.node_ids,s,db)
@app.get('/reports/hosts/{node_id}/export')
def report_host_export(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)):
    if not report_service.host_detail(db,s.id,node_id): raise HTTPException(404,'REPORT_HOST_NOT_FOUND')
    path=report_service.export_report(db,s.id,node_id); return FileResponse(path,filename=path.name)

_service_config_nodes={}
def _service_job_dict(job,db):
    rows=db.scalars(select(ServiceConfigResult).where(ServiceConfigResult.job_id==job.id)).all()
    nodes={n.id:n for n in db.scalars(select(Node).where(Node.id.in_([x.node_id for x in rows]))).all()}
    fallback=f'Service {job.operation.title()} - {(job.started_at or job.created_at):%Y-%m-%d %H:%M}'
    return {'job_id':job.id,'job_name':job.job_name or fallback,'operation':job.operation,'created_at':job.created_at,'started_at':job.started_at,'finished_at':job.finished_at,'status':job.status,'restart_requested':job.restart_requested,'total':job.total_nodes,'completed':job.completed_nodes,'success':job.success_nodes,'error':job.failed_nodes,'progress_percent':round(job.completed_nodes*100/job.total_nodes,1) if job.total_nodes else 0,'nodes':[{'node_id':x.node_id,'node_name':(nodes.get(x.node_id).node_id or nodes.get(x.node_id).hostname) if nodes.get(x.node_id) else None,'address':nodes.get(x.node_id).address if nodes.get(x.node_id) else None,'status':x.status,'kill_mode':x.new_kill_mode or x.previous_kill_mode,'restart_status':x.restart_status,'error_code':x.error_code,'error_message':x.error_message} for x in rows]}
def _execute_service_job(job_id):
    db=SessionLocal()
    try:
        job=db.get(ServiceConfigJob,job_id)
        if not job or job.status=='CANCELLED': return
        session=db.get(Session,job.session_id); ids=_service_config_nodes.pop(job_id,[])
        nodes=db.scalars(select(Node).where(Node.session_id==session.id,Node.id.in_(ids))).all()
        operation,restart_requested=job.operation,job.restart_requested
        ssh_session=SimpleNamespace(id=session.id,tsh_version=session.tsh_version)
        targets=[SimpleNamespace(id=node.id,hostname=node.hostname) for node in nodes]
        rollback_sources={}
        if operation=='ROLLBACK':
            for target in targets:
                old=db.scalar(select(ServiceConfigResult).where(ServiceConfigResult.node_id==target.id,ServiceConfigResult.operation=='CONFIGURE').order_by(ServiceConfigResult.id.desc()))
                rollback_sources[target.id]=(old.backup_path if old else '',old.previous_override_exists if old else False)
        job.status='RUNNING'; job.started_at=datetime.utcnow(); db.commit()
        def work(target):
            if operation=='CHECK': return target,service_config.check_node(ssh_session,target)
            if operation=='CONFIGURE': return target,service_config.configure_node(ssh_session,target,restart_requested)
            backup,previous_exists=rollback_sources[target.id]
            return target,service_config.rollback_node(ssh_session,target,backup,previous_exists)
        batch_size=max(1,settings.service_config_batch_size)
        for start_index in range(0,len(targets),batch_size):
            batch=targets[start_index:start_index+batch_size]
            with ThreadPoolExecutor(max_workers=min(settings.service_config_max_concurrency,len(batch))) as pool:
                for future in as_completed([pool.submit(work,target) for target in batch]):
                    node,value=future.result(); job=db.get(ServiceConfigJob,job_id); ok=value.get('status') in {'CONFIGURED','NOT_CONFIGURED','SUCCESS','SKIPPED_ALREADY_CONFIGURED'}
                    db.add(ServiceConfigResult(job_id=job.id,node_id=node.id,operation=operation,previous_kill_mode=value.get('previous_kill_mode') or value.get('kill_mode'),new_kill_mode=value.get('new_kill_mode') or value.get('kill_mode'),config_method='override' if operation!='CHECK' else None,previous_override_exists=value.get('previous_override_exists'),backup_path=value.get('backup_path'),restart_requested=restart_requested,restart_status=value.get('restart_status'),service_state_before=value.get('service_state'),service_state_after=value.get('service_state'),main_pid_before=value.get('main_pid'),main_pid_after=value.get('main_pid'),status=value.get('status','ERROR'),error_code=value.get('error_code'),error_message=value.get('error_message'),started_at=datetime.utcnow(),finished_at=datetime.utcnow())); job.completed_nodes+=1; job.success_nodes+=int(ok); job.failed_nodes+=int(not ok); db.commit()
                    if restart_requested:
                        restart_status=value.get('restart_status') or 'NOT_ATTEMPTED'
                        audit(db,session,'TELEPORT_RESTART','NODE',1,job.id,'SUCCESS' if restart_status=='SUCCESS' else 'FAILED',f'node_id={node.id}; restart_status={restart_status}')
        job.status='COMPLETED'; job.finished_at=datetime.utcnow(); db.commit()
    except Exception as exc:
        db.rollback(); j=db.get(ServiceConfigJob,job_id)
        if j: j.status='FAILED';j.finished_at=datetime.utcnow();db.commit()
        log.exception('service_config_job_failed job_id=%s',job_id)
    finally: db.close()
def _create_service_job(body,operation,s,db):
    if operation=='CONFIGURE' and body.method!='override': raise HTTPException(422,'INVALID_CONFIG_METHOD')
    ids=list(dict.fromkeys(body.node_ids))
    if len(ids)>settings.service_config_max_nodes_per_request: raise HTTPException(400,'TOO_MANY_NODES')
    if len(set(db.scalars(select(Node.id).where(Node.session_id==s.id,Node.id.in_(ids))).all()))!=len(ids): raise HTTPException(404,'NODE_NOT_FOUND')
    name=(body.job_name or '').strip()
    if name and any(ord(ch)<32 for ch in name): raise HTTPException(422,'INVALID_JOB_NAME')
    name=name or f'Service {operation.title()} - {datetime.utcnow():%Y-%m-%d %H:%M}'
    j=ServiceConfigJob(id=str(uuid.uuid4()),session_id=s.id,created_by=s.username,job_name=name,operation=operation,status='QUEUED',restart_requested=body.restart_after_apply if operation=='CONFIGURE' else False,total_nodes=len(ids),created_at=datetime.utcnow());db.add(j);db.commit();_service_config_nodes[j.id]=ids;threading.Thread(target=_execute_service_job,args=(j.id,),daemon=True).start();return {'job_id':j.id,'job_name':j.job_name,'job_type':f'SERVICE_{operation}','status':'QUEUED','total_nodes':len(ids),'restart_requested':j.restart_requested}
@app.get('/service-config/nodes')
def service_nodes(search:str='',status:str='',page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),s:Session=Depends(active),db:Db=Depends(db_session)):
    term=search.strip(); stmt=select(Node).where(Node.session_id==s.id)
    if term: stmt=stmt.where(or_(Node.hostname.ilike(f'%{term}%'),Node.node_id.ilike(f'%{term}%'),Node.address.ilike(f'%{term}%'),cast(Node.labels,String).ilike(f'%{term}%')))
    latest=select(ServiceConfigResult.node_id,func.max(ServiceConfigResult.id).label('id')).group_by(ServiceConfigResult.node_id).subquery()
    config=select(ServiceConfigResult).join(latest,ServiceConfigResult.id==latest.c.id).subquery()
    if status: stmt=stmt.join(config,Node.id==config.c.node_id,isouter=True).where(config.c.status==status)
    total=db.scalar(select(func.count()).select_from(stmt.subquery())); rows=db.scalars(stmt.order_by(Node.hostname).offset((page-1)*page_size).limit(page_size)).all(); items=[]
    for n in rows:
        r=db.scalar(select(ServiceConfigResult).where(ServiceConfigResult.node_id==n.id).order_by(ServiceConfigResult.id.desc()))
        items.append({**serialize_node(n),'kill_mode':r.new_kill_mode if r else None,'config_status':r.status if r else 'UNKNOWN','service_state':r.service_state_after if r else None,'last_check':r.finished_at if r else None})
    return {'items':items,'total':total,'page':page,'page_size':page_size}
@app.post('/service-config/check')
def service_check(body:ServiceConfigRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'OPERATOR','ADMIN'); value=_create_service_job(body,'CHECK',s,db); audit(db,s,'SERVICE_CHECK_CREATE','NODE',len(body.node_ids),value['job_id']); return value
@app.post('/service-config/configure')
def service_configure(body:ServiceConfigRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'ADMIN'); value=_create_service_job(body,'CONFIGURE',s,db); audit(db,s,'SERVICE_CONFIG_CREATE','NODE',len(body.node_ids),value['job_id']); return value
@app.post('/service-config/rollback')
def service_rollback(body:ServiceConfigRequest,s:Session=Depends(active),db:Db=Depends(db_session)):
    require(s,'ADMIN')
    value=_create_service_job(body,'ROLLBACK',s,db); audit(db,s,'SERVICE_ROLLBACK_CREATE','NODE',len(body.node_ids),value['job_id']); return value
@app.get('/service-config/jobs/{job_id}')
def service_job(job_id:str,s:Session=Depends(active),db:Db=Depends(db_session)):
    j=db.get(ServiceConfigJob,job_id)
    if not j or j.session_id!=s.id: raise HTTPException(404,'SERVICE_CONFIG_JOB_NOT_FOUND')
    return _service_job_dict(j,db)
@app.get('/service-config/history')
def service_history(s:Session=Depends(active),db:Db=Depends(db_session)): return [_service_job_dict(j,db) for j in db.scalars(select(ServiceConfigJob).where(ServiceConfigJob.session_id==s.id).order_by(ServiceConfigJob.created_at.desc())).all()]

def _config_rows(s,db,search='',status='',operation='',restart_status=''):
    nodes=db.scalars(select(Node).where(Node.session_id==s.id)).all(); out=[]
    for n in nodes:
        results=db.scalars(select(ServiceConfigResult).join(ServiceConfigJob,ServiceConfigResult.job_id==ServiceConfigJob.id).where(ServiceConfigResult.node_id==n.id,ServiceConfigJob.session_id==s.id).order_by(ServiceConfigResult.finished_at.desc(),ServiceConfigResult.id.desc())).all()
        if not results: continue
        r=results[0]; j=db.get(ServiceConfigJob,r.job_id); term=search.lower()
        if term and term not in ' '.join([n.hostname or '',n.node_id or '',n.address or '',str(n.labels or {}),j.job_name or '']).lower(): continue
        cfg='CONFIGURED' if r.new_kill_mode=='process' and r.status in ('CONFIGURED','SUCCESS','SKIPPED_ALREADY_CONFIGURED') else ('ERROR' if r.status not in ('CONFIGURED','NOT_CONFIGURED','SUCCESS','SKIPPED_ALREADY_CONFIGURED') else 'NOT_CONFIGURED')
        if status and cfg!=status: continue
        if operation and r.operation!=operation: continue
        if restart_status and (r.restart_status or 'NOT_REQUESTED')!=restart_status: continue
        out.append({'node_id':n.id,'node_name':n.node_id or n.hostname,'hostname':n.hostname,'ip':n.address,'labels':n.labels or {},'kill_mode':r.new_kill_mode or r.previous_kill_mode,'config_status':cfg,'last_operation':'SERVICE_'+r.operation,'job_id':j.id,'job_name':j.job_name or f'Service {j.operation.title()} - {j.created_at:%Y-%m-%d %H:%M}','restart_status':r.restart_status or 'NOT_REQUESTED','service_state':r.service_state_after or r.service_state_before or 'unknown','last_updated':r.finished_at or j.finished_at,'last_configured':r.finished_at if r.operation=='CONFIGURE' and cfg=='CONFIGURED' else None})
    return out
@app.get('/config-report/summary')
def config_report_summary(s:Session=Depends(active),db:Db=Depends(db_session)):
    rows=_config_rows(s,db); return {'total_nodes':len(rows),'configured':sum(x['config_status']=='CONFIGURED' for x in rows),'not_configured':sum(x['config_status']=='NOT_CONFIGURED' for x in rows),'error':sum(x['config_status']=='ERROR' for x in rows),'unknown':0,'restart_success':sum(x['restart_status']=='SUCCESS' for x in rows),'restart_failed':sum(x['restart_status'] not in ('SUCCESS','NOT_REQUESTED') for x in rows)}
@app.get('/config-report/nodes')
def config_report_nodes(search:str='',status:str='',operation:str='',restart_status:str='',page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),s:Session=Depends(active),db:Db=Depends(db_session)):
    rows=_config_rows(s,db,search,status,operation,restart_status); start=(page-1)*page_size; return {'items':rows[start:start+page_size],'total':len(rows),'page':page,'page_size':page_size}
@app.get('/config-report/nodes/{node_id}')
def config_report_node(node_id:int,s:Session=Depends(active),db:Db=Depends(db_session)):
    n=db.scalar(select(Node).where(Node.id==node_id,Node.session_id==s.id)); rows=_config_rows(s,db); current=next((x for x in rows if x['node_id']==node_id),None)
    if not n or not current: raise HTTPException(404,'CONFIG_REPORT_NOT_FOUND')
    hist=[]
    for r in db.scalars(select(ServiceConfigResult).join(ServiceConfigJob,ServiceConfigResult.job_id==ServiceConfigJob.id).where(ServiceConfigResult.node_id==node_id,ServiceConfigJob.session_id==s.id).order_by(ServiceConfigResult.finished_at.desc())).all():
        j=db.get(ServiceConfigJob,r.job_id); hist.append({**current,'job_id':j.id,'job_name':j.job_name,'operation':'SERVICE_'+r.operation,'previous_kill_mode':r.previous_kill_mode,'new_kill_mode':r.new_kill_mode,'restart_requested':r.restart_requested,'restart_status':r.restart_status or 'NOT_REQUESTED','service_state_before':r.service_state_before,'service_state_after':r.service_state_after,'status':r.status,'error':r.error_message,'started_at':j.started_at,'finished_at':j.finished_at})
    return {'node':current,'history':hist}
@app.post('/config-report/export')
def config_report_export(body:dict,s:Session=Depends(active),db:Db=Depends(db_session)):
    ids=list(dict.fromkeys(body.get('node_ids') or [])); rows=_config_rows(s,db,body.get('search',''),body.get('status',''),body.get('operation',''),body.get('restart_status','')); selected=[x for x in rows if not ids or x['node_id'] in ids]
    if body.get('node_ids') is not None and not ids: raise HTTPException(400,'EMPTY_NODE_IDS')
    wb=Workbook(); ws=wb.active; ws.title='01_Summary'; ws.append(['Generated At','Selected Nodes','Configured','Not Configured','Error','Restart Success','Restart Failed']); ws.append([datetime.utcnow(),len(selected),sum(x['config_status']=='CONFIGURED' for x in selected),sum(x['config_status']=='NOT_CONFIGURED' for x in selected),sum(x['config_status']=='ERROR' for x in selected),sum(x['restart_status']=='SUCCESS' for x in selected),sum(x['restart_status'] not in ('SUCCESS','NOT_REQUESTED') for x in selected)])
    nws=wb.create_sheet('02_Nodes'); nws.append(['No','Node Name','Hostname','IP','KillMode','Config Status','Last Operation','Job Name','Restart Status','Service State','Last Updated']);
    for i,x in enumerate(selected,1): nws.append([i,x['node_name'],x['hostname'],x['ip'],x['kill_mode'],x['config_status'],x['last_operation'],x['job_name'],x['restart_status'],x['service_state'],x['last_updated']])
    for sh in wb.worksheets:
        sh.freeze_panes='A2'; sh.auto_filter.ref=sh.dimensions
        for c in sh[1]: c.font=Font(bold=True); c.alignment=Alignment(wrap_text=True)
    path=settings.export_root/f'teleport_config_report_{datetime.utcnow():%Y%m%d_%H%M%S}.xlsx'; wb.save(path); audit(db,s,'REPORT_EXPORT','SERVICE_CONFIGURATION',len(selected)); return FileResponse(path,filename=path.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
