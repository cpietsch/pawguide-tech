#!/usr/bin/env bash
set -euo pipefail

environment_path="${PAWGUIDE_ENV_FILE:-/etc/pawguide/pawguide.env}"
if [[ -r "${environment_path}" ]]; then
  # shellcheck disable=SC1090
  source "${environment_path}"
fi
if [[ "${PAWGUIDE_ADAPTER:-mock}" != "dimos_mcp" ]]; then
  exit 0
fi

mcp_url="${PAWGUIDE_DIMOS_MCP_URL:-http://127.0.0.1:9990/mcp}"
for _attempt in $(seq 1 180); do
  if curl \
    --fail \
    --silent \
    --max-time 1 \
    --header 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":"gateway-readiness","method":"tools/list","params":{}}' \
    "${mcp_url}" |
    /opt/dimos/bin/python \
      /opt/pawguide/bin/check-dimos-tools.py \
      --physical-minimal \
      --quiet; then
    exit 0
  fi
  sleep 1
done

echo "DimOS MCP did not expose the required physical tools at ${mcp_url}." >&2
exit 1
