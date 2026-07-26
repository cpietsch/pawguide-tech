#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

wifi_interface="${PAWGUIDE_WIFI_INTERFACE:-wlan0}"
connection_name="${PAWGUIDE_WIFI_CONNECTION:-go2-ap-client}"
robot_ip="${PAWGUIDE_ROBOT_IP:-192.168.12.1}"
robot_bssid="${PAWGUIDE_ROBOT_BSSID:-}"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "NetworkManager/nmcli is not installed." >&2
  exit 1
fi
if ! ip link show "${wifi_interface}" >/dev/null 2>&1; then
  echo "Wi-Fi interface ${wifi_interface} is missing." >&2
  echo "Confirm the selected edge computer has a supported Wi-Fi interface." >&2
  exit 1
fi

if ! nmcli -t -f NAME connection show | grep -Fxq "${connection_name}"; then
  read -rp "Go2 AP SSID: " robot_ssid
  if [[ -z "${robot_ssid}" ]]; then
    echo "SSID must not be empty." >&2
    exit 1
  fi
  nmcli connection add \
    type wifi \
    ifname "${wifi_interface}" \
    con-name "${connection_name}" \
    ssid "${robot_ssid}"
fi

nmcli connection modify "${connection_name}" \
  connection.autoconnect yes \
  connection.interface-name "${wifi_interface}" \
  ipv4.method auto \
  ipv4.never-default yes \
  ipv4.ignore-auto-dns yes \
  ipv6.method disabled \
  802-11-wireless.powersave 2 \
  wifi-sec.key-mgmt wpa-psk
if [[ -n "${robot_bssid}" ]]; then
  if [[ ! "${robot_bssid}" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]]; then
    echo "PAWGUIDE_ROBOT_BSSID must be a six-byte MAC address." >&2
    exit 1
  fi
  nmcli connection modify "${connection_name}" \
    802-11-wireless.bssid "${robot_bssid}" \
    802-11-wireless.hidden yes
fi

echo "Network profile prepared. NetworkManager will now ask for the AP password."
nmcli --ask connection up "${connection_name}"

echo "Robot route:"
ip -4 route get "${robot_ip}"
echo "Default route:"
ip -4 route show default
