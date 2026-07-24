#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

environment_path=/etc/pawguide/pawguide.env
if [[ -r /etc/pawguide/dev.token ]]; then
  dev_token="$(</etc/pawguide/dev.token)"
  command_id="$(</proc/sys/kernel/random/uuid)"
  curl \
    --fail \
    --silent \
    --max-time 5 \
    --header "Authorization: Bearer ${dev_token}" \
    --header 'Content-Type: application/json' \
    --data "{\"command_id\":\"${command_id}\",\"action\":\"stop\",\"arguments\":{}}" \
    http://127.0.0.1:8765/v1/commands \
    >/dev/null 2>&1 || true
  unset dev_token
fi

sed -i \
  -e 's/^PAWGUIDE_ADAPTER=.*/PAWGUIDE_ADAPTER=mock/' \
  -e 's/^PAWGUIDE_ENABLE_REAL_MOTION=.*/PAWGUIDE_ENABLE_REAL_MOTION=NO/' \
  "${environment_path}"
systemctl restart pawguide-gateway.service
systemctl disable --now pawguide-dimos.service

echo "Real motion disabled; the gateway is back in mock mode."
