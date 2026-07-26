#!/usr/bin/env bash
set -u

failures=0
warnings=0
require_physical=0
if [[ "${1:-}" == "--require-physical" ]]; then
  require_physical=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--require-physical]" >&2
  exit 2
fi
if [[ -r /etc/pawguide/pawguide.env ]]; then
  # Root-owned deployment settings; includes file paths but no secret values.
  # shellcheck disable=SC1091
  source /etc/pawguide/pawguide.env
fi
wifi_interface="${PAWGUIDE_WIFI_INTERFACE:-wlan0}"
robot_ip="${PAWGUIDE_ROBOT_IP:-192.168.12.1}"

pass() {
  printf 'PASS  %s\n' "$1"
}

warn() {
  printf 'WARN  %s\n' "$1"
  warnings=$((warnings + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  failures=$((failures + 1))
}

if [[ "$(uname -m)" == "aarch64" ]]; then
  pass "architecture is aarch64"
else
  fail "architecture is $(uname -m), expected aarch64"
fi

hardware_identity="$(
  {
    if [[ -r /proc/device-tree/model ]]; then
      tr -d '\0' </proc/device-tree/model
      echo
    fi
    if [[ -r /etc/version ]]; then
      cat /etc/version
    fi
    if command -v rdkos_info >/dev/null 2>&1; then
      rdkos_info
    fi
  } 2>/dev/null
)"
if [[ "${hardware_identity,,}" == *"x5"* ]]; then
  pass "RDK X5 hardware is identified"
else
  fail "device tree and RDK OS metadata do not identify an RDK X5"
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${VERSION_ID:-}" == "22.04" ]]; then
    pass "RDK OS base is Ubuntu 22.04"
  else
    warn "OS version is ${VERSION_ID:-unknown}; validate against the RDK image release"
  fi
else
  fail "/etc/os-release is unavailable"
fi

memory_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
if [[ "${memory_kib:-0}" -ge 7000000 ]]; then
  pass "at least 7 GB usable RAM detected"
else
  fail "less than 7 GB usable RAM detected; expected the 8 GB RDK X5"
fi

available_kib="$(df --output=avail /opt 2>/dev/null | tail -n 1 | tr -d ' ')"
if [[ "${available_kib:-0}" -ge 10000000 ]]; then
  pass "at least 10 GB free under /opt"
else
  fail "less than 10 GB free under /opt"
fi

if [[ -r /etc/pawguide/hardware-profile ]] &&
  [[ "$(< /etc/pawguide/hardware-profile)" == "x5" ]]; then
  pass "installed PawGuide hardware profile is x5"
else
  fail "installed PawGuide hardware profile is not x5"
fi

if ip link show "${wifi_interface}" >/dev/null 2>&1; then
  pass "onboard Wi-Fi interface ${wifi_interface} exists"
else
  fail "Wi-Fi interface ${wifi_interface} does not exist"
fi

robot_route="$(ip -4 route get "${robot_ip}" 2>/dev/null)"
if [[ "${robot_route}" == *"dev ${wifi_interface}"* ]]; then
  pass "${robot_ip} routes over ${wifi_interface}"
else
  fail "${robot_ip} does not route over ${wifi_interface}"
fi

default_route="$(ip -4 route show default 2>/dev/null | head -n 1)"
default_interface="$(
  sed -n 's/.* dev \([^ ]*\).*/\1/p' <<<"${default_route}" |
    head -n 1
)"
if [[ -z "${default_route}" ]]; then
  fail "no IPv4 default route is installed"
elif [[ "${default_route}" == *"dev ${wifi_interface}"* ]]; then
  fail "Go2 Wi-Fi is the default route; Pixel USB or Ethernet should own it"
else
  pass "default route is independent of Go2 Wi-Fi"
fi

uplink_interface="${PAWGUIDE_UPLINK_INTERFACE:-}"
if [[ -n "${uplink_interface}" ]]; then
  if [[ "${default_interface}" == "${uplink_interface}" ]]; then
    pass "configured uplink ${uplink_interface} owns the default route"
  else
    fail "configured uplink ${uplink_interface} does not own the default route"
  fi
elif [[ "${default_interface}" == usb* || "${default_interface}" == enx* ]]; then
  pass "default route appears to use Pixel USB tethering (${default_interface})"
else
  warn "default route uses ${default_interface:-unknown}; confirm this is the intended uplink"
fi

if ping -c 1 -W 2 "${robot_ip}" >/dev/null 2>&1; then
  pass "Go2 AP address responds"
else
  fail "Go2 AP address does not respond"
fi

if tailscale status >/dev/null 2>&1; then
  pass "Tailscale is online"
else
  fail "Tailscale is not online"
fi

if systemctl is-active --quiet pawguide-gateway.service; then
  pass "PawGuide gateway service is active"
else
  fail "PawGuide gateway service is not active"
fi

if curl --fail --silent --max-time 2 http://127.0.0.1:8765/health >/dev/null; then
  pass "PawGuide gateway health endpoint responds"
else
  fail "PawGuide gateway health endpoint does not respond"
fi

if [[ -x /opt/pawguide/.venv/bin/pawguide-operator ]]; then
  pass "no-LLM manual operator console is installed"
else
  fail "manual operator console is not installed"
fi

if [[ -x /opt/dimos/bin/dimos ]]; then
  pass "pinned DimOS edge runtime is installed"
else
  fail "DimOS edge runtime is not installed"
fi

adapter_mode="unknown"
if [[ -r /etc/pawguide/pawguide.env ]]; then
  adapter_mode="$(
    sed -n 's/^PAWGUIDE_ADAPTER=//p' /etc/pawguide/pawguide.env |
      tail -n 1
  )"
fi
if [[ "${adapter_mode}" == "dimos_mcp" ]]; then
  if systemctl is-active --quiet pawguide-dimos.service; then
    pass "DimOS physical service is active for the real adapter"
  else
    fail "real adapter is selected but DimOS is inactive"
  fi
  if curl \
    --fail \
    --silent \
    --max-time 2 \
    --header 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":"readiness","method":"tools/list","params":{}}' \
    http://127.0.0.1:9990/mcp |
    /opt/dimos/bin/python \
      /opt/pawguide/bin/check-dimos-tools.py \
      --quiet; then
    pass "DimOS MCP endpoint exposes every required PawGuide tool"
  else
    fail "DimOS MCP endpoint is unavailable or missing required tools"
  fi
elif systemctl is-active --quiet pawguide-dimos.service; then
  warn "DimOS physical service is active while the gateway is not using it"
else
  pass "physical DimOS service remains inactive in mock mode"
fi

temperature_count="$(
  find /sys/class/thermal \
    -maxdepth 2 \
    -type f \
    -name 'temp' \
    2>/dev/null |
    wc -l
)"
if [[ "${temperature_count}" -ge 1 ]]; then
  pass "RDK thermal sensors are exposed"
else
  warn "no thermal-zone temperature sensor was found"
fi

for secret_path in /etc/pawguide/operator.token /etc/pawguide/dev.token; do
  if [[ ! -f "${secret_path}" ]]; then
    fail "${secret_path} is missing"
    continue
  fi
  secret_mode="$(stat -c '%a' "${secret_path}")"
  secret_owner="$(stat -c '%U:%G' "${secret_path}")"
  if [[ "${secret_mode}" == "640" && "${secret_owner}" == "root:pawguide" ]]; then
    pass "${secret_path} ownership and mode are correct"
  else
    fail "${secret_path} must be mode 640 and root:pawguide"
  fi
done

robot_secret=/etc/pawguide/unitree-aes.token
if [[ -f "${robot_secret}" ]]; then
  secret_mode="$(stat -c '%a' "${robot_secret}")"
  secret_owner="$(stat -c '%U:%G' "${robot_secret}")"
  if [[ "${secret_mode}" == "640" && "${secret_owner}" == "root:pawguide" ]]; then
    pass "robot credential ownership and mode are correct"
  else
    fail "robot credential must be mode 640 and root:pawguide"
  fi
else
  if [[ "${require_physical}" -eq 1 ]]; then
    fail "robot credential is not installed; physical DimOS cannot start"
  else
    warn "robot credential is not installed; physical DimOS cannot start"
  fi
fi

warn "software cannot validate the 5 V/5 A supply, cooling airflow, payload mass or connector retention"

printf '\nSummary: %d failure(s), %d warning(s)\n' "${failures}" "${warnings}"
if [[ "${failures}" -ne 0 ]]; then
  exit 1
fi
