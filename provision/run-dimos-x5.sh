#!/usr/bin/env bash
set -euo pipefail

# Physical direct-Go2 runtime entry point for the RDK X5.
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
exec /opt/dimos/bin/python /opt/pawguide/bin/direct-go2-mcp.py
