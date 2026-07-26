#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root on the China server." >&2
  exit 1
fi

x5_host="${PAWGUIDE_X5_SSH_HOST:-sunrise@100.72.30.53}"
token_path=/etc/pawguide/x5-operator.token
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install -d -o root -g root -m 0750 /etc/pawguide

token_tmp="$(mktemp /etc/pawguide/.x5-operator.token.XXXXXX)"
trap 'rm -f -- "${token_tmp}"' EXIT
chmod 0600 "${token_tmp}"
ssh \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  "${x5_host}" \
  "sudo -n cat /etc/pawguide/operator.token" >"${token_tmp}"
if ! grep -Eq '^[0-9a-f]{64}$' "${token_tmp}"; then
  echo "The X5 operator token has an invalid format." >&2
  exit 1
fi
mv -f -- "${token_tmp}" "${token_path}"
trap - EXIT

"${script_dir}/install-admin-auth.sh" "${token_path}"
nginx -t
systemctl reload nginx.service
echo "China nginx authentication now uses the X5 operator credential."
