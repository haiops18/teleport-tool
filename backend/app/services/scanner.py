import base64, re, shlex
from .teleport import run
from ..config import settings

# Snapshot the cgroup once. Afterwards process ancestry is read from /proc, so
# metadata helpers spawned by this script do not enter the snapshot.
SCRIPT=r'''set -eu
SCANNER_PID=$$
cg=$(systemctl show teleport.service -p ControlGroup --value) || { echo "ERR\tTELEPORT_SERVICE_NOT_FOUND"; exit 0; }
kill_mode=$(systemctl show teleport.service -p KillMode --value) || { echo "ERR\tKILLMODE_UNKNOWN"; exit 0; }
[ -n "$cg" ] || { echo "ERR\tCGROUP_NOT_FOUND"; exit 0; }
[ -n "$kill_mode" ] || { echo "ERR\tKILLMODE_UNKNOWN"; exit 0; }
if [ "$(stat -fc %T /sys/fs/cgroup 2>/dev/null || true)" = cgroup2fs ]; then f=/sys/fs/cgroup$cg/cgroup.procs; else f=$(find /sys/fs/cgroup -path "*$cg/cgroup.procs" -type f 2>/dev/null | head -1); fi
[ -r "${f:-}" ] || { echo "ERR\tCGROUP_NOT_FOUND"; exit 0; }
pids=''; while IFS= read -r pid; do case "$pid" in *[!0-9]*|'') continue;; esac; [ -d "/proc/$pid" ] && pids="$pids $pid"; done < "$f"
ppids=''
for pid in $pids; do ppid=''; while IFS= read -r line; do case "$line" in PPid:*) ppid=${line#PPid:}; set -- $ppid; ppid=${1:-};; esac; done < "/proc/$pid/status" 2>/dev/null || true; ppids="$ppids $pid:$ppid"; done
internal=" $SCANNER_PID "; changed=1
while [ "$changed" = 1 ]; do changed=0; for pair in $ppids; do pid=${pair%%:*}; ppid=${pair#*:}; case "$internal" in *" $pid "*) continue;; esac; case "$internal" in *" $ppid "*) internal="$internal$pid "; changed=1;; esac; done; done
# The tsh command may add a teleport exec wrapper above the scanner shell. Mark
# only this request's ancestor chain (never other historical Teleport sessions).
parent=$SCANNER_PID
while :; do parent_ppid=''; for pair in $ppids; do pid=${pair%%:*}; ppid=${pair#*:}; [ "$pid" = "$parent" ] && { parent_ppid=$ppid; break; }; done; [ -n "$parent_ppid" ] && [ "$parent_ppid" != 0 ] || break; case "$internal" in *" $parent_ppid "*) break;; esac; internal="$internal$parent_ppid "; parent=$parent_ppid; done
# Discover every active `teleport exec` root in this snapshot, then recursively
# add its current descendants. No process name is used as a safety allow-list.
session_roots=''
for pid in $pids; do
  [ -d "/proc/$pid" ] || continue
  exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null || true); cmd=$(tr '\000' ' ' <"/proc/$pid/cmdline" 2>/dev/null)
  [ "$exe" = /usr/local/bin/teleport ] || continue
  case "$cmd" in *' exec '|*' exec') session_roots="$session_roots $pid";; esac
done
sessions=''
for root in $session_roots; do
  sessions="$sessions $root "; changed=1
  while [ "$changed" = 1 ]; do changed=0; for pair in $ppids; do pid=${pair%%:*}; ppid=${pair#*:}; case "$sessions" in *" $pid "*) continue;; esac; case "$sessions" in *" $ppid "*) sessions="$sessions$pid "; changed=1;; esac; done; done
done
for pid in $pids; do
  [ -d "/proc/$pid" ] || continue
  ppid=''; while IFS= read -r line; do case "$line" in PPid:*) ppid=${line#PPid:}; set -- $ppid; ppid=${1:-};; esac; done < "/proc/$pid/status" 2>/dev/null || continue
  exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null || true); cmd=$(tr '\000' ' ' <"/proc/$pid/cmdline" 2>/dev/null); meta=$(ps -p "$pid" -o user=,etime= 2>/dev/null | awk '{$1=$1;print}')
  [ -n "$meta" ] || continue; user=${meta%% *}; runtime=${meta#* }; class=RISK
  if [ "$exe" = /usr/local/bin/teleport ]; then case "$cmd" in *' start '*|start*) class=TELEPORT_CORE;; esac; fi
  [ "$class" = TELEPORT_CORE ] || case "$internal" in *" $pid "*) class=SCAN_INTERNAL;; esac
  [ "$class" = RISK ] && case "$sessions" in *" $pid "*) class=TELEPORT_SESSION;; esac
  [ "$class" = RISK ] && [ "$kill_mode" = process ] && class=EXTERNAL_PROTECTED
  encoded_cmd=$(printf '%s' "$cmd" | base64 | tr -d '\n')
  printf 'PROC\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pid" "$ppid" "$user" "$runtime" "$exe" "$encoded_cmd" "$cg" "$class" "$kill_mode"
done'''

_SENSITIVE_ARGUMENT=re.compile(r'(?i)(--(?:token|auth-token|join-token|password)(?:=|\s+))\S+')

def _redact_command(command: str) -> str:
    return _SENSITIVE_ARGUMENT.sub(r'\1********',command)

def scan_node(session, node):
    """Persist only actual risks; current scanner tree never becomes a risk."""
    result=run(session.id,session.tsh_version,['ssh',f'root@{node.hostname}','sh -c '+shlex.quote(SCRIPT)],timeout=settings.scan_timeout_seconds)
    if result.returncode:
        return 'UNREACHABLE',[{'status':'UNREACHABLE','error_message':(result.stderr or 'NODE_UNREACHABLE')[-2000:]}]
    risks=[]; protected=[]
    for line in result.stdout.splitlines():
        fields=line.split('\t')
        if fields[0]=='ERR': return 'ERROR',[{'status':'ERROR','error_message':fields[1] if len(fields)>1 else 'SCAN_FAILED'}]
        if len(fields)<10 or fields[0]!='PROC': continue
        _,pid,ppid,user,runtime,exe,encoded_command,cgroup,classification,kill_mode=fields[:10]
        try:
            cmd=_redact_command(base64.b64decode(encoded_command,validate=True).decode('utf-8','replace'))
        except (ValueError, UnicodeError):
            # A malformed record must never be turned into a false SAFE result.
            return 'ERROR',[{'status':'ERROR','error_message':'SCAN_PROTOCOL_INVALID'}]
        if classification not in {'RISK','EXTERNAL_PROTECTED'}: continue
        finding={'status':'WARNING' if classification=='RISK' else 'SAFE','pid':int(pid),'ppid':int(ppid or 0),'username':user,'runtime':runtime,'executable':exe,'command_line':cmd,'cgroup_path':cgroup,'classification':classification,'kill_mode':kill_mode,'risk':'Process is inside teleport.service cgroup and is not Teleport core, an active Teleport session, or the current scanner execution.' if classification=='RISK' else 'External process exists in teleport.service cgroup, but effective KillMode=process prevents systemd from terminating the whole cgroup during Teleport service stop/restart.'}
        (risks if classification=='RISK' else protected).append(finding)
    # A detached application tree can contain transient helpers (for example a
    # worker's `sleep 5`). Persist only each independent risk root; descendants
    # remain classified remotely as RISK but do not inflate the warning count.
    def roots(values):
        pids={value['pid'] for value in values}
        return [value for value in values if value['ppid'] not in pids]
    root_risks,root_protected=roots(risks),roots(protected)
    results=root_risks+root_protected
    return ('WARNING' if root_risks else 'SAFE'), (results or [{'status':'SAFE','kill_mode':kill_mode}])
