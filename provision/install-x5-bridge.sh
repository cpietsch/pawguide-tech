#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=rdk-x5-platform.sh
source "${script_dir}/rdk-x5-platform.sh"
pawguide_require_rdk_x5

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is missing; run bootstrap-rdk-x5.sh first." >&2
  exit 1
fi

bundle_dir="$(cd -- "${script_dir}/.." && pwd)"
wheel_files=("${bundle_dir}"/dist/pawguide-*.whl)
if [[ "${#wheel_files[@]}" -ne 1 || ! -f "${wheel_files[0]}" ]]; then
  echo "Expected exactly one PawGuide wheel under ${bundle_dir}/dist." >&2
  exit 1
fi
requirements_file="${bundle_dir}/dist/requirements-edge.txt"
if [[ ! -f "${requirements_file}" ]]; then
  echo "Missing pinned dependency file: ${requirements_file}" >&2
  exit 1
fi

if ! id pawguide >/dev/null 2>&1; then
  useradd \
    --system \
    --create-home \
    --home-dir /var/lib/pawguide \
    --shell /usr/sbin/nologin \
    pawguide
fi

install -d -o root -g root -m 0755 /opt/pawguide
install -d -o pawguide -g pawguide -m 0750 /var/lib/pawguide
install -d -o root -g pawguide -m 0750 /etc/pawguide

if [[ ! -x /opt/pawguide/.venv/bin/python ]]; then
  uv venv --python 3.12 /opt/pawguide/.venv
fi
uv pip install \
  --python /opt/pawguide/.venv/bin/python \
  --upgrade \
  --requirement "${requirements_file}"
uv pip install \
  --python /opt/pawguide/.venv/bin/python \
  --upgrade \
  --no-deps \
  "${wheel_files[0]}"

for token_name in operator dev; do
  token_path="/etc/pawguide/${token_name}.token"
  if [[ ! -e "${token_path}" ]]; then
    openssl rand -hex -out "${token_path}" 32
  fi
  chown root:pawguide "${token_path}"
  chmod 0640 "${token_path}"
done

if [[ ! -e /etc/pawguide/pawguide.env ]]; then
  install \
    -o root \
    -g pawguide \
    -m 0640 \
    "${bundle_dir}/config/pawguide.env.example" \
    /etc/pawguide/pawguide.env
  sed -i \
    "s/PAWGUIDE_BIND_HOST=replace-with-bind-address/PAWGUIDE_BIND_HOST=0.0.0.0/" \
    /etc/pawguide/pawguide.env
fi

printf 'x5\n' > /etc/pawguide/hardware-profile
chown root:pawguide /etc/pawguide/hardware-profile
chmod 0640 /etc/pawguide/hardware-profile

install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-gateway.service" \
  /etc/systemd/system/pawguide-gateway.service

systemctl daemon-reload
systemctl enable --now pawguide-gateway.service

echo "PawGuide X5 mock gateway and manual operator console installed."
echo "The real adapter remains double-gated and disabled."
echo "Run: sudo ${script_dir}/check-x5-readiness.sh"
