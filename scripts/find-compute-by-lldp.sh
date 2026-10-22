#!/usr/bin/env bash
# Determine an OpenStack/virtualization compute name advertised to a VM via LLDP.
# Usage: ./find-compute-by-lldp.sh <teleport-node> [login] [seconds] [interface]
set -Eeuo pipefail

NODE="${1:?Usage: $0 <teleport-node> [login] [seconds] [interface]}"
LOGIN="${2:-root}"
SECONDS="${3:-60}"
INTERFACE="${4:-}"
TSH_BIN="${TSH_BIN:-tsh}"
PROXY_ARGS=()
[[ -n "${TELEPORT_PROXY:-}" ]] && PROXY_ARGS=("--proxy=${TELEPORT_PROXY}")

remote_script='set -eu
timeout_seconds="$1"
requested_dev="$2"
if [ -n "$requested_dev" ]; then
  dev="$requested_dev"
else
  dev="$(ip route show default 2>/dev/null | awk "NR==1 {for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}}")"
fi
[ -n "$dev" ] && ip link show "$dev" >/dev/null 2>&1 || { echo "ERROR: interface not found" >&2; exit 2; }
case "$dev" in lo|docker*|br-*|veth*|virbr*|cni*|flannel*|tun*|tap*) echo "ERROR: $dev is not a VM uplink NIC" >&2; exit 2;; esac

echo "=== LLDP capture: $dev (${timeout_seconds}s) ==="
timeout "$timeout_seconds" tcpdump -l -eni "$dev" ether proto 0x88cc || true'

output="$("$TSH_BIN" "${PROXY_ARGS[@]}" ssh "${LOGIN}@${NODE}" \
  "sh -c $(printf '%q' "$remote_script") sh $(printf '%q' "$SECONDS") $(printf '%q' "$INTERFACE")" 2>&1 || true)"
printf '%s\n' "$output"

# A compute name is normally the hostname in the LLDP payload, conventionally
# `*-comp-*`. The second LLDP record is often the VM advertising its own UUID.
compute="$(printf '%s\n' "$output" | grep -Eo '[[:alnum:]._-]*comp-[[:alnum:]._-]*' | head -n1 || true)"
if [ -n "$compute" ]; then
  printf '\nCOMPUTE_HOST=%s\n' "$compute"
else
  printf '\nCOMPUTE_HOST=NOT_DETECTED\n' >&2
  exit 1
fi
