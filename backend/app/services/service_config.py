"""Safe, backend-defined systemd Teleport KillMode management."""
import shlex, time
from datetime import datetime
from .teleport import run
from ..config import settings

CHECK_SCRIPT=r'''set -eu
systemctl show teleport.service >/dev/null 2>&1 || { echo 'ERR|SERVICE_NOT_FOUND'; exit 0; }
v(){ systemctl show teleport.service -p "$1" --value 2>/dev/null || true; }
printf 'OK|%s|%s|%s|%s|%s|%s\n' "$(v KillMode)" "$(v ActiveState)" "$(v SubState)" "$(v MainPID)" "$(v FragmentPath)" "$(v DropInPaths)"'''

APPLY_SCRIPT=r'''set -eu
systemctl show teleport.service >/dev/null 2>&1 || { echo 'ERR|SERVICE_NOT_FOUND'; exit 0; }
d=/etc/systemd/system/teleport.service.d; f=$d/override.conf; old=$(systemctl show teleport.service -p KillMode --value)
if [ "$old" = process ]; then echo 'SKIP|process'; exit 0; fi
mkdir -p "$d"; existed=0; backup=''
if [ -f "$f" ]; then existed=1; backup="$f.bak.$(date +%Y%m%d%H%M%S)"; cp -p "$f" "$backup"; fi
t=$(mktemp "$d/.override.XXXXXX")
if [ -f "$f" ]; then grep -v '^[[:space:]]*KillMode[[:space:]]*=' "$f" > "$t" || true; fi
printf '\n[Service]\nKillMode=process\n' >> "$t"; install -m 0644 "$t" "$f"; rm -f "$t"
systemctl daemon-reload || { echo "ERR|DAEMON_RELOAD_FAILED|$existed|$backup"; exit 0; }
new=$(systemctl show teleport.service -p KillMode --value)
[ "$new" = process ] || { echo "ERR|VERIFY_FAILED|$existed|$backup|$new"; exit 0; }
echo "OK|$old|$new|$existed|$backup"'''

ROLLBACK_SCRIPT=r'''set -eu
systemctl show teleport.service >/dev/null 2>&1 || { echo 'ERR|SERVICE_NOT_FOUND'; exit 0; }
f=/etc/systemd/system/teleport.service.d/override.conf; backup="$1"; existed="$2"
if [ "$existed" = true ]; then [ -n "$backup" ] && [ -f "$backup" ] || { echo 'ERR|BACKUP_NOT_FOUND'; exit 0; }; cp -p "$backup" "$f"; else rm -f "$f"; fi
systemctl daemon-reload || { echo 'ERR|DAEMON_RELOAD_FAILED'; exit 0; }
echo "OK|$(systemctl show teleport.service -p KillMode --value)"'''

def _remote(session,node,script,timeout=None):
    result=run(session.id,session.tsh_version,['ssh',f'root@{node.hostname}','sh -c '+shlex.quote(script)],timeout=timeout or settings.scan_timeout_seconds)
    if result.returncode: return {'status':'ERROR','error_code':'SSH_ERROR','error_message':(result.stderr or 'SSH_ERROR')[-1000:]}
    parts=result.stdout.strip().split('|')
    if not parts or parts[0]=='ERR': return {'status':'ERROR','error_code':parts[1] if len(parts)>1 else 'CHECK_FAILED','error_message':'Remote systemctl command failed'}
    return {'parts':parts}

def check_node(session,node):
    data=_remote(session,node,CHECK_SCRIPT)
    if 'status' in data: return data
    p=data['parts']; return {'status':'CONFIGURED' if p[1]=='process' else 'NOT_CONFIGURED','kill_mode':p[1],'service_state':p[2],'sub_state':p[3],'main_pid':p[4],'fragment_path':p[5],'drop_in_paths':p[6] if len(p)>6 else ''}

def configure_node(session,node,restart=False):
    before=check_node(session,node)
    if before.get('status')=='ERROR': return before
    applied=_remote(session,node,APPLY_SCRIPT)
    if 'status' in applied: return {**before,**applied}
    p=applied['parts']
    if p[0]=='SKIP': return {**before,'status':'SKIPPED_ALREADY_CONFIGURED','new_kill_mode':'process'}
    result={**before,'status':'SUCCESS','previous_kill_mode':p[1],'new_kill_mode':p[2],'previous_override_exists':p[3]=='1','backup_path':p[4] if len(p)>4 else '', 'restart_status':'NOT_REQUESTED'}
    if not restart: return result
    # Fresh effective check immediately before a destructive restart.
    final=check_node(session,node)
    if final.get('kill_mode')!='process': return {**result,'status':'RESTART_BLOCKED','restart_status':'BLOCKED'}
    restart_result=run(session.id,session.tsh_version,['ssh',f'root@{node.hostname}','systemctl restart teleport.service'],timeout=settings.scan_timeout_seconds)
    # A disconnect is normal. Reconnect using the existing tsh transport.
    deadline=time.monotonic()+settings.teleport_restart_max_wait
    while time.monotonic()<deadline:
        time.sleep(settings.teleport_restart_retry_interval)
        after=check_node(session,node)
        if after.get('status')!='ERROR':
            if after.get('kill_mode')=='process' and after.get('service_state')=='active': return {**result,**after,'status':'SUCCESS','restart_status':'SUCCESS'}
            return {**result,**after,'status':'FINAL_VERIFY_FAILED','restart_status':'FAILED'}
    return {**result,'status':'RECONNECT_TIMEOUT','restart_status':'TIMEOUT'}

def rollback_node(session,node,backup_path,previous_exists):
    command='sh -c '+shlex.quote(ROLLBACK_SCRIPT)+' -- '+shlex.quote(backup_path or '')+' '+shlex.quote(str(bool(previous_exists)).lower())
    result=run(session.id,session.tsh_version,['ssh',f'root@{node.hostname}',command],timeout=settings.scan_timeout_seconds)
    if result.returncode: return {'status':'ERROR','error_code':'SSH_ERROR','error_message':(result.stderr or 'SSH_ERROR')[-1000:]}
    p=result.stdout.strip().split('|')
    return {'status':'SUCCESS' if p and p[0]=='OK' else 'ERROR','new_kill_mode':p[1] if len(p)>1 else None,'error_code':p[1] if p and p[0]=='ERR' and len(p)>1 else None}
