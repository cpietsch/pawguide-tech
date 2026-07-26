#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0 [--enable]" >&2
  exit 1
fi
if [[ "${1:-}" != "" && "${1:-}" != "--enable" ]]; then
  echo "Usage: sudo $0 [--enable]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=rdk-x5-platform.sh
source "${script_dir}/rdk-x5-platform.sh"
pawguide_require_rdk_x5

if [[ ! -x /opt/pawguide/.venv/bin/pawguide-gateway ]]; then
  echo "Install the X5 bridge before the simulation services." >&2
  exit 1
fi
if ! command -v socat >/dev/null 2>&1; then
  apt-get update
  apt-get install -y socat
fi

install -d -o root -g pawguide -m 0750 /etc/pawguide
sim_env_tmp="$(mktemp /etc/pawguide/.pawguide-sim.env.XXXXXX)"
trap 'rm -f -- "${sim_env_tmp}"' EXIT
install \
  -o root \
  -g pawguide \
  -m 0640 \
  "${script_dir}/x5/pawguide-sim-concept.env" \
  "${sim_env_tmp}"
tail_ip="$(tailscale ip -4 | head -n1)"
if [[ ! "${tail_ip}" =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Could not resolve the X5 Tailscale IPv4 address." >&2
  exit 1
fi
sed -i \
  "s/^PAWGUIDE_BIND_HOST=.*/PAWGUIDE_BIND_HOST=${tail_ip}/" \
  "${sim_env_tmp}"
mv -f -- "${sim_env_tmp}" /etc/pawguide/pawguide-sim.env
trap - EXIT

install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/x5/pawguide-sim-mcp-relay.service" \
  /etc/systemd/system/pawguide-sim-mcp-relay.service
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/x5/pawguide-sim-gateway.service" \
  /etc/systemd/system/pawguide-sim-gateway.service
systemctl daemon-reload

if [[ "${1:-}" == "--enable" ]]; then
  systemctl enable --now \
    pawguide-sim-mcp-relay.service \
    pawguide-sim-gateway.service
  echo "X5 simulation gateway enabled at http://${tail_ip}:8876."
else
  echo "X5 simulation units installed but not enabled."
  echo "Enable later with:"
  echo "  sudo systemctl enable --now pawguide-sim-mcp-relay.service pawguide-sim-gateway.service"
fi
