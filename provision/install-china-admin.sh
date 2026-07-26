#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root on the China server." >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
token_path="${PAWGUIDE_X5_OPERATOR_TOKEN_FILE:-/etc/pawguide/x5-operator.token}"

apt-get update
apt-get install -y nginx openssh-client
install -d -o root -g root -m 0755 /var/www/pawguide
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-admin-dashboard.html" \
  /var/www/pawguide/dashboard.html
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-admin-dashboard.js" \
  /var/www/pawguide/dashboard.js
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-admin.nginx.conf" \
  /etc/nginx/sites-available/pawguide-admin
ln -sfn \
  /etc/nginx/sites-available/pawguide-admin \
  /etc/nginx/sites-enabled/pawguide-admin
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-hyper-tunnel.service" \
  /etc/systemd/system/pawguide-hyper-tunnel.service

if [[ ! -s "${token_path}" ]]; then
  echo "Missing ${token_path}." >&2
  echo "Run provision/sync-x5-operator-token.sh first." >&2
  exit 1
fi
"${script_dir}/install-admin-auth.sh" "${token_path}"

systemctl daemon-reload
systemctl enable nginx.service
if [[ -s /root/.ssh/pawguide_gpu_server ]]; then
  systemctl enable --now pawguide-hyper-tunnel.service
else
  echo "Hyper SSH key is absent; installed but did not enable the simulator tunnel."
fi
nginx -t
systemctl restart nginx.service
echo "China PawGuide admin installed at http://100.102.208.90:7780/command-center."
