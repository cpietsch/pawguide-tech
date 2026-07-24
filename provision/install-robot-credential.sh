#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

install -d -o root -g pawguide -m 0750 /etc/pawguide
read -rsp "Unitree AES key: " robot_aes_key
echo

if [[ ! "${robot_aes_key}" =~ ^[[:xdigit:]]{32}$ ]]; then
  unset robot_aes_key
  echo "Expected exactly 32 hexadecimal characters." >&2
  exit 1
fi

temporary_path="$(mktemp /etc/pawguide/.unitree-aes.XXXXXX)"
trap 'rm -f -- "${temporary_path}"' EXIT
printf '%s\n' "${robot_aes_key}" > "${temporary_path}"
unset robot_aes_key
chown root:pawguide "${temporary_path}"
chmod 0640 "${temporary_path}"
mv -f -- "${temporary_path}" /etc/pawguide/unitree-aes.token
trap - EXIT

echo "Robot credential installed at /etc/pawguide/unitree-aes.token."
