#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "LCM network configuration must run as root." >&2
  exit 1
fi

ip link set lo multicast on
ip route replace 224.0.0.0/4 dev lo
sysctl -q -w net.core.rmem_max=67108864
sysctl -q -w net.core.rmem_default=67108864
