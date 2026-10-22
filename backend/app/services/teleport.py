import json, os, re, subprocess, pexpect, logging
from datetime import datetime
from pathlib import Path
from fastapi import HTTPException
from ..config import settings
log=logging.getLogger(__name__)
ANSI_RE=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
def clean_text(value): return ANSI_RE.sub('',value or '').strip()
def binary(version):
    p=settings.tsh_binaries.get(version)
    if not p or not Path(p).is_file() or not os.access(p,os.X_OK): raise HTTPException(400,'TSH_BINARY_NOT_FOUND')
    return p
def env(session_id): return {**os.environ,'TELEPORT_HOME':str(settings.session_root/session_id),'HOME':str(settings.session_root/session_id)}
def login(session_id, proxy, version, username, password, otp):
    cmd=[binary(version),'login',f'--proxy={proxy}',f'--user={username}']
    log.info('LOGIN_COMMAND_STARTED version=%s proxy=%s session_id=%s home=%s',version,proxy,session_id,env(session_id).get('TELEPORT_HOME'))
    child=pexpect.spawn(cmd[0],cmd[1:],env=env(session_id),encoding='utf-8',timeout=30)
    try:
        while True:
            i=child.expect([r'(?i)password.*:',r'(?i)(one.?time|otp|token|verification).*:',r'(?i)(success|logged in)',pexpect.EOF,pexpect.TIMEOUT])
            if i==0: child.sendline(password)
            elif i==1:
                if not otp: raise RuntimeError('OTP_REQUIRED')
                child.sendline(otp)
            elif i==2: continue
            elif i==3:
                child.close()
                log.info('LOGIN_COMMAND_EXIT_CODE version=%s session_id=%s code=%s',version,session_id,child.exitstatus)
                if child.exitstatus != 0:
                    raise HTTPException(401,clean_text(child.before)[-240:] or 'TSH_LOGIN_FAILED')
                return
            else: raise RuntimeError('TSH_LOGIN_TIMEOUT')
    except Exception as e:
        child.close(force=True); msg=clean_text(getattr(child,'before',''))
        log.info('LOGIN_COMMAND_FAILED version=%s session_id=%s error=%s',version,session_id,msg[-240:])
        if isinstance(e,HTTPException): raise e
        raise HTTPException(401, 'OTP_REQUIRED' if str(e)=='OTP_REQUIRED' else ('TSH_LOGIN_TIMEOUT' if str(e)=='TSH_LOGIN_TIMEOUT' else (msg[-240:] or 'TSH_LOGIN_FAILED')))
def run(session_id, version, args, timeout=30):
    try: return subprocess.run([binary(version),*args],env=env(session_id),capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired: raise HTTPException(504,'SSH_TIMEOUT')
def status(session_id, version):
    r=run(session_id,version,['status'],15)
    if r.returncode:
        # A failed post-login status check is not necessarily an expired app session.
        # Preserve a safe, actionable error instead of masking proxy/network failures.
        detail=clean_text(r.stderr or r.stdout).replace('\n',' ')[:240]
        raise HTTPException(502, f'TELEPORT_STATUS_FAILED: {detail or "tsh status returned non-zero"}')
    text=r.stdout; fields={}
    for k in ('Cluster','Logged in as','Roles','Valid until'):
        m=re.search(rf'(?im)^\s*{re.escape(k)}\s*:\s*(.+)$',text)
        if m: fields[k]=m.group(1).strip()
    return fields
def list_nodes(session_id, version):
    r=run(session_id,version,['ls','--format=json'],30)
    if r.returncode==0:
        try: return normalize_nodes(json.loads(r.stdout))
        except json.JSONDecodeError: pass
    r=run(session_id,version,['ls'],30)
    if r.returncode: raise HTTPException(502,'NODE_LIST_FAILED')
    lines=[x.split() for x in r.stdout.splitlines()[1:] if x.strip()]
    return [{'hostname':x[0],'addr':x[1] if len(x)>1 else None} for x in lines]
def normalize_nodes(payload):
    """Convert tsh JSON from supported client versions into one stable shape."""
    if isinstance(payload,dict):
        payload=payload.get('nodes') or payload.get('items') or payload.get('resources') or []
    if not isinstance(payload,list): return []
    nodes=[]
    for raw in payload:
        if not isinstance(raw,dict): continue
        meta=raw.get('metadata') if isinstance(raw.get('metadata'),dict) else {}
        spec=raw.get('spec') if isinstance(raw.get('spec'),dict) else {}
        hostname=raw.get('hostname') or spec.get('hostname') or meta.get('name') or raw.get('name')
        if not hostname: continue
        nodes.append({
            'hostname':hostname,
            'addr':raw.get('addr') or raw.get('address') or spec.get('addr') or spec.get('address'),
            'node_id':raw.get('id') or raw.get('node_id') or meta.get('id'),
            'cluster':raw.get('cluster_name') or raw.get('cluster') or spec.get('cluster_name'),
            'labels':raw.get('labels') or meta.get('labels') or {},
            'teleport_version':raw.get('version') or spec.get('version'),
        })
    return nodes
