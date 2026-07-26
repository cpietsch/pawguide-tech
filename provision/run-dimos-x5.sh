#!/usr/bin/env bash
set -euo pipefail

# Physical DimOS runtime entry point for the RDK X5.
credential_path="${CREDENTIALS_DIRECTORY:-}/unitree_aes"
if [[ -z "${CREDENTIALS_DIRECTORY:-}" || ! -r "${credential_path}" ]]; then
  echo "The Unitree credential was not supplied by systemd." >&2
  exit 1
fi

export UNITREE_AES_128_KEY
UNITREE_AES_128_KEY="$(<"${credential_path}")"
if [[ ! "${UNITREE_AES_128_KEY}" =~ ^[[:xdigit:]]{32}$ ]]; then
  echo "The Unitree credential has an invalid format." >&2
  exit 1
fi
robot_ip="${PAWGUIDE_ROBOT_IP:-192.168.12.1}"
physical_mcp_port="${PAWGUIDE_DIMOS_MCP_PORT:-9990}"

if [[ "${PAWGUIDE_ENABLE_PULSEAUDIO:-NO}" == "YES" ]] &&
  ! pulseaudio --check >/dev/null 2>&1; then
  pulseaudio --start --exit-idle-time=-1
fi

if [[ "${PAWGUIDE_DIMOS_PROFILE:-sport}" == "sport" ]]; then
  exec /opt/dimos/bin/python /opt/pawguide/bin/direct-go2-mcp.py
fi

exec /opt/dimos/bin/python /opt/pawguide/bin/run-dimos-local-ap.py \
  --transport lcm \
  --viewer none \
  --robot-ip "${robot_ip}" \
  --unitree-webrtc-connection-method local_ap \
  --listen-host 127.0.0.1 \
  --mcp-port "${physical_mcp_port}" \
  run \
  unitree-go2-basic \
  replanning-a-star-planner \
  unitree-skill-container \
  mcp-server \
  --disable perceive-loop-skill \
  --disable websocket-vis-module
