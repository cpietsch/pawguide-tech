#!/usr/bin/env bash
set -euo pipefail

# Read-only DimOS diagnostics for the RDK X5 edge runtime.
dimos_bin="${PAWGUIDE_DIMOS_BIN:-/opt/dimos/bin/dimos}"
robot_ip="${PAWGUIDE_ROBOT_IP:-192.168.12.1}"
mcp_url="${PAWGUIDE_DIMOS_MCP_URL:-http://127.0.0.1:9990/mcp}"

if [[ ! -x "${dimos_bin}" ]]; then
  echo "DimOS is not installed at ${dimos_bin}." >&2
  exit 1
fi

echo "Resolved safe runtime settings:"
"${dimos_bin}" \
  --transport lcm \
  --viewer none \
  --robot-ip "${robot_ip}" \
  --unitree-webrtc-connection-method local_ap \
  show-config |
  sed -n \
    -e '/^robot_ip:/p' \
    -e '/^unitree_webrtc_connection_method:/p' \
    -e '/^viewer:/p' \
    -e '/^mcp_port:/p' \
    -e '/^transport:/p'

echo
echo "Systemd state:"
systemctl is-active pawguide-dimos.service

echo
echo "MCP status:"
"${dimos_bin}" mcp status

echo
echo "Deployed modules:"
"${dimos_bin}" mcp modules

echo
echo "Required PawGuide tools:"
"${dimos_bin}" mcp list-tools |
  "${dimos_bin%/dimos}/python" \
    /opt/pawguide/bin/check-dimos-tools.py

echo
echo "Direct MCP endpoint:"
curl \
  --fail \
  --silent \
  --show-error \
  --max-time 2 \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":"diagnostic","method":"initialize","params":{}}' \
  "${mcp_url}" >/dev/null
echo "PASS  ${mcp_url}"
