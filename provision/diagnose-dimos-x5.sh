#!/usr/bin/env bash
set -euo pipefail

# Read-only diagnostics for the current direct-Go2 X5 runtime.
if [[ -r /etc/pawguide/pawguide.env ]]; then
  # shellcheck disable=SC1091
  source /etc/pawguide/pawguide.env
fi
robot_ip="${PAWGUIDE_ROBOT_IP:-192.168.12.1}"
mcp_url="${PAWGUIDE_DIMOS_MCP_URL:-http://127.0.0.1:9990/mcp}"
python_bin=/opt/dimos/bin/python

if [[ ! -x "${python_bin}" ]]; then
  echo "The pinned X5 Python environment is missing at ${python_bin}." >&2
  exit 1
fi

echo "Robot route:"
ip -4 route get "${robot_ip}"

echo
echo "Service state:"
systemctl is-active pawguide-dimos.service pawguide-gateway.service

echo
echo "Physical MCP tool gate:"
curl \
  --fail \
  --silent \
  --show-error \
  --max-time 3 \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":"diagnostic","method":"tools/list","params":{}}' \
  "${mcp_url}" |
  "${python_bin}" \
    /opt/pawguide/bin/check-dimos-tools.py \
    --physical-minimal

echo
echo "Gateway health:"
curl --fail --silent --show-error --max-time 3 \
  http://127.0.0.1:8765/health
echo
