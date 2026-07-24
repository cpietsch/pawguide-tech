#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=rdk-s100-platform.sh
source "${script_dir}/rdk-s100-platform.sh"
pawguide_require_rdk_s100

apt-get update
apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  git-lfs \
  libturbojpeg0 \
  network-manager \
  openssl \
  patch \
  portaudio19-dev \
  pulseaudio \
  python3-dev \
  python3-venv \
  ufw

if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

if ! id pawguide >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pawguide --shell /usr/sbin/nologin pawguide
fi

install -d -o pawguide -g pawguide -m 0750 /var/lib/pawguide
install -d -o root -g pawguide -m 0750 /etc/pawguide

echo
echo "RDK S100 base packages installed."
echo "Next:"
echo "  1. Install/verify a supported M.2 Key-E Wi-Fi module, then run provision/configure-go2-ap.sh."
echo "  2. Connect the Pixel to a USB-A host port and enable USB tethering for the default route."
echo "  3. Join Tailscale with a one-off tagged auth key."
echo "  4. Run provision/install-s100-bridge.sh."
echo "  5. Run provision/install-dimos-s100.sh (installs but does not enable motion)."
echo "  6. Run provision/check-s100-readiness.sh."
echo
echo "Before network use, replace the image's default sunrise/root passwords."
if systemctl is-enabled display-manager.service >/dev/null 2>&1; then
  echo "WARN: A desktop display manager is enabled. Use the Server image for headless PawGuide."
fi
