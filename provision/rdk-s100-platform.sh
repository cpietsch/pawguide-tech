#!/usr/bin/env bash

pawguide_rdk_s100_identity() {
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
}

pawguide_require_rdk_s100() {
  if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "Expected aarch64 RDK S100; found $(uname -m)." >&2
    return 1
  fi

  if [[ ! -r /etc/os-release ]]; then
    echo "Cannot identify the operating system." >&2
    return 1
  fi

  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
    echo "Expected RDK S100 OS based on Ubuntu 22.04; found ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
    return 1
  fi

  local hardware_identity
  hardware_identity="$(pawguide_rdk_s100_identity)"
  if [[ "${hardware_identity,,}" != *"s100"* ]]; then
    echo "Device tree and RDK OS metadata do not identify an RDK S100." >&2
    return 1
  fi
}
