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

if ! pulseaudio --check >/dev/null 2>&1; then
  pulseaudio --start --exit-idle-time=-1
fi

exec /opt/dimos/bin/dimos \
  --transport lcm \
  --viewer none \
  --robot-ip 192.168.12.1 \
  --unitree-webrtc-connection-method local_ap \
  run \
  unitree-go2 \
  unitree-skill-container \
  paw-guide-waypoint-skill \
  mcp-server \
  --disable perceive-loop-skill \
  --disable websocket-vis-module
