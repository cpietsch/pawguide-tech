#!/usr/bin/env bash
set -euo pipefail

confirmation="--i-understand-this-can-move-the-robot"
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0 ${confirmation}" >&2
  exit 1
fi
if [[ "${1:-}" != "${confirmation}" ]]; then
  echo "Refusing to enable physical motion without ${confirmation}" >&2
  exit 1
fi
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
profile_path=/etc/pawguide/hardware-profile
if [[ ! -r "${profile_path}" ]]; then
  echo "Missing ${profile_path}; reinstall the edge bridge for this board." >&2
  exit 1
fi
hardware_profile="$(<"${profile_path}")"
case "${hardware_profile}" in
  x5)
    # shellcheck source=rdk-x5-platform.sh
    source "${script_dir}/rdk-x5-platform.sh"
    pawguide_require_rdk_x5
    ;;
  s100)
    # shellcheck source=rdk-s100-platform.sh
    source "${script_dir}/rdk-s100-platform.sh"
    pawguide_require_rdk_s100
    ;;
  *)
    echo "Unknown PawGuide hardware profile: ${hardware_profile}" >&2
    exit 1
    ;;
esac
if [[ ! -f /etc/pawguide/unitree-aes.token ]]; then
  echo "Install the robot credential first." >&2
  exit 1
fi
if ! ping -c 1 -W 2 192.168.12.1 >/dev/null 2>&1; then
  echo "The Go2 AP is not reachable at 192.168.12.1." >&2
  exit 1
fi
if [[ ! -x /opt/pawguide/bin/check-x5-readiness.sh ]]; then
  echo "The installed X5 readiness gate is missing." >&2
  exit 1
fi
if ! /opt/pawguide/bin/check-x5-readiness.sh --require-physical; then
  echo "Physical readiness failed; real motion remains disabled." >&2
  exit 1
fi

systemctl enable --now pawguide-dimos.service
dim_os_ready=0
for _attempt in $(seq 1 120); do
  if curl \
    --fail \
    --silent \
    --max-time 1 \
    --header 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":"readiness","method":"tools/list","params":{}}' \
    http://127.0.0.1:9990/mcp |
    /opt/dimos/bin/python \
      /opt/pawguide/bin/check-dimos-tools.py \
      --quiet; then
    dim_os_ready=1
    break
  fi
  sleep 1
done
if [[ "${dim_os_ready}" -ne 1 ]] || ! systemctl is-active --quiet pawguide-dimos.service; then
  echo "DimOS did not become ready; the gateway remains in its previous mode." >&2
  systemctl disable --now pawguide-dimos.service
  exit 1
fi

environment_path=/etc/pawguide/pawguide.env
environment_backup="$(mktemp /etc/pawguide/.pawguide.env.XXXXXX)"
cp --preserve=mode,ownership "${environment_path}" "${environment_backup}"
rollback() {
  set +e
  mv -f -- "${environment_backup}" "${environment_path}"
  systemctl restart pawguide-gateway.service
  systemctl disable --now pawguide-dimos.service
  echo "Real-adapter enable failed and was rolled back to the previous gateway mode." >&2
}
trap rollback ERR

sed -i \
  -e 's/^PAWGUIDE_ADAPTER=.*/PAWGUIDE_ADAPTER=dimos_mcp/' \
  -e 's/^PAWGUIDE_ENABLE_REAL_MOTION=.*/PAWGUIDE_ENABLE_REAL_MOTION=YES/' \
  "${environment_path}"
systemctl restart pawguide-gateway.service
for _attempt in $(seq 1 20); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:8765/health |
    grep -q '"motion_capable":true'; then
    break
  fi
  sleep 1
done
curl --fail --silent --max-time 2 http://127.0.0.1:8765/health |
  grep -q '"motion_capable":true'

trap - ERR
unlink "${environment_backup}"

echo "Real adapter enabled. The gateway has restarted with STOP latched."
echo "Do not reset the latch until the supported-off-ground test is ready."
