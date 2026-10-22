"""Read-only LLDP based compute-host discovery via Teleport SSH."""
import re
from ..config import settings
from .teleport import run

COMPUTE_RE = re.compile(r'(?<![\w.-])([\w.-]*comp-[\w.-]*)(?![\w.-])', re.I)

def classify_discovery_failure(returncode, stdout, stderr):
    """Map transport/LLDP outcomes to one stable, user-visible explanation."""
    text=(stderr or stdout or '').strip(); lower=text.lower()
    if not returncode:
        if not text: return 'NOT_DETECTED','EMPTY_OUTPUT','LLDP command completed but returned no neighbor data.'
        return 'NOT_DETECTED','NO_COMPUTE_NEIGHBOR','LLDP neighbors were found, but none matched the configured compute identification rules.'
    if any(x in lower for x in ('connection timed out','no route to host','connection refused','could not resolve','dial tcp')):
        return 'UNREACHABLE','SSH_FAILED','Teleport could not establish an SSH connection to this node.'
    if 'timed out' in lower or 'ssh_timeout' in lower:
        return 'UNREACHABLE','SSH_TIMEOUT','Teleport SSH or LLDP capture timed out before completion.'
    if any(x in lower for x in ('tcpdump: not found','command not found')):
        return 'ERROR','LLDP_COMMAND_NOT_FOUND','The LLDP capture command is not available on this node.'
    if 'permission denied' in lower:
        return 'ERROR','SSH_FAILED','The remote command was rejected by permissions or Teleport policy.'
    return 'ERROR','UNKNOWN','The LLDP discovery command failed unexpectedly.'

# Each capture is isolated so output retains the NIC that received the LLDP frame.
SCRIPT = r'''set -eu
dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
default=$(ip route show default 2>/dev/null | awk 'NR==1 {for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1);exit}}')
devs=''
for p in /sys/class/net/*; do
  n=${p##*/}
  case "$n" in lo|docker*|br-*|veth*|virbr*|cni*|flannel*|tun*|tap*) continue;; esac
  ip link show "$n" >/dev/null 2>&1 || continue
  devs="$devs $n"
done
[ -n "$default" ] && devs="$default $(printf '%s\n' $devs | awk -v d="$default" '$0!=d')"
for dev in $devs; do timeout "${DISCOVERY_CAPTURE_SECONDS:-60}" tcpdump -l -eni "$dev" ether proto 0x88cc >"$dir/$dev" 2>&1 & done
wait || true
for dev in $devs; do echo "__NIC__:$dev"; cat "$dir/$dev" 2>/dev/null || true; done'''

def discover(session, node):
    result = run(session.id, session.tsh_version,
                 ['ssh', f'root@{node.hostname}', 'DISCOVERY_CAPTURE_SECONDS=' + str(settings.discovery_scan_timeout_seconds) + ' sh -c ' + __import__('shlex').quote(SCRIPT)],
                 timeout=max(settings.discovery_scan_timeout_seconds + 15, 75))
    current = None
    matches = []
    for line in (result.stdout or '').splitlines():
        if line.startswith('__NIC__:'):
            current = line.split(':', 1)[1]
            continue
        found = COMPUTE_RE.search(line)
        if found and current:
            matches.append((current, found.group(1)))
    if matches:
        nic, compute = matches[0]
        return {'node_id': node.id, 'hostname': node.hostname, 'address': node.address,
                'nic': nic, 'compute': compute, 'status': 'DETECTED', 'failed_stage':None, 'reason_code':None, 'reason_message':None, 'command_exit_code':result.returncode}
    detail = (result.stderr or result.stdout or 'LLDP_NOT_DETECTED').strip()[-500:]
    status, reason_code, reason_message=classify_discovery_failure(result.returncode,result.stdout,result.stderr)
    return {'node_id': node.id, 'hostname': node.hostname, 'address': node.address,
            'nic': None, 'compute': None, 'status': status, 'failed_stage':'COMPUTE_MATCH' if status=='NOT_DETECTED' else 'TELEPORT_CONNECT', 'reason_code':reason_code, 'reason_message':reason_message, 'command_exit_code':result.returncode, 'detail': detail}
