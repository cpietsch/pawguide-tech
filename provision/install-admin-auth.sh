#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

token_path="${1:-/etc/pawguide/operator.token}"
auth_config="/etc/pawguide/nginx-operator-auth.conf"
if [[ ! -s "${token_path}" ]]; then
  echo "Missing operator token: ${token_path}" >&2
  exit 1
fi

operator_token="$(tr -d '\r\n' <"${token_path}")"
if [[ ! "${operator_token}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Operator token has an invalid format." >&2
  exit 1
fi

auth_tmp="$(mktemp /etc/pawguide/nginx-operator-auth.conf.XXXXXX)"
chmod 0600 "${auth_tmp}"
chown root:root "${auth_tmp}"
printf 'proxy_set_header Authorization "Bearer %s";\n' \
  "${operator_token}" >"${auth_tmp}"
mv -f "${auth_tmp}" "${auth_config}"
