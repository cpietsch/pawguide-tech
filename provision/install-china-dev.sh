#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 <release-id> <staging-directory>" >&2
  exit 1
fi

release_id="$1"
staging_dir="$2"
if [[ ! "${release_id}" =~ ^[0-9a-f]{12}$ ]]; then
  echo "Release ID must be exactly 12 lowercase hexadecimal characters." >&2
  exit 1
fi
if [[ ! -d "${staging_dir}" ]]; then
  echo "Staging directory does not exist: ${staging_dir}" >&2
  exit 1
fi

source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "Expected Ubuntu 24.04; found ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
  exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "The China development deployment expects x86_64." >&2
  exit 1
fi
if ! systemctl is-active --quiet tailscaled.service; then
  echo "tailscaled.service must be active." >&2
  exit 1
fi

cd "${staging_dir}"
sha256sum --check SHA256SUMS

wheel_files=("${staging_dir}"/pawguide-*.whl)
if [[ "${#wheel_files[@]}" -ne 1 || ! -f "${wheel_files[0]}" ]]; then
  echo "Expected exactly one PawGuide wheel in ${staging_dir}." >&2
  exit 1
fi
for required_file in \
  requirements-edge.txt \
  pawguide-source.tar.gz \
  pawguide-china-gateway.service \
  pawguide-china-resolved.conf \
  dev.token; do
  if [[ ! -f "${staging_dir}/${required_file}" ]]; then
    echo "Missing deployment input: ${required_file}" >&2
    exit 1
  fi
done
if ! grep -Eq '^[0-9a-f]{64}$' "${staging_dir}/dev.token"; then
  echo "The development token has an invalid format." >&2
  exit 1
fi

install -d -o root -g root -m 0755 /etc/systemd/resolved.conf.d
install \
  -o root \
  -g root \
  -m 0644 \
  "${staging_dir}/pawguide-china-resolved.conf" \
  /etc/systemd/resolved.conf.d/60-pawguide-china.conf
systemctl restart systemd-resolved.service
resolvectl flush-caches
if ! timeout 15 getent ahostsv4 pypi.org >/dev/null; then
  echo "DNS remains unavailable after installing the resolver override." >&2
  exit 1
fi

# The image's cloud-only mirror resolves to another unreachable 100.100.2.x
# service address. Preserve the original once, then use Aliyun's public HTTPS
# mirror, which is reachable from this instance without an exit node.
apt_sources="/etc/apt/sources.list"
if grep -q 'mirrors\.cloud\.aliyuncs\.com/ubuntu' "${apt_sources}"; then
  if [[ ! -e "${apt_sources}.before-pawguide" ]]; then
    cp -a "${apt_sources}" "${apt_sources}.before-pawguide"
  fi
  sed -i \
    's#http://mirrors\.cloud\.aliyuncs\.com/ubuntu#https://mirrors.aliyun.com/ubuntu#g' \
    "${apt_sources}"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  openssl \
  python3-venv

# The image ships the same unreachable cloud-only hostname in root's pip
# configuration. Keep a recovery copy and point interactive use at the public
# HTTPS endpoint as well; the release install also supplies the index
# explicitly so it is independent of user configuration.
pip_config="/root/.pip/pip.conf"
if [[ -f "${pip_config}" ]] &&
  grep -q 'mirrors\.cloud\.aliyuncs\.com/pypi' "${pip_config}"; then
  if [[ ! -e "${pip_config}.before-pawguide" ]]; then
    cp -a "${pip_config}" "${pip_config}.before-pawguide"
  fi
  sed -i \
    's#http://mirrors\.cloud\.aliyuncs\.com/pypi/simple/#https://mirrors.aliyun.com/pypi/simple/#g; s#mirrors\.cloud\.aliyuncs\.com#mirrors.aliyun.com#g' \
    "${pip_config}"
fi

if ! id pawguide >/dev/null 2>&1; then
  useradd \
    --system \
    --create-home \
    --home-dir /var/lib/pawguide \
    --shell /usr/sbin/nologin \
    pawguide
fi

release_dir="/opt/pawguide/releases/${release_id}"
source_dir="/srv/pawguide/releases/${release_id}"
install -d -o root -g root -m 0755 \
  /opt/pawguide \
  /opt/pawguide/releases \
  /srv/pawguide \
  /srv/pawguide/releases \
  "${release_dir}" \
  "${source_dir}"
install -d -o pawguide -g pawguide -m 0750 /var/lib/pawguide
install -d -o root -g pawguide -m 0750 /etc/pawguide

tar -xzf "${staging_dir}/pawguide-source.tar.gz" -C "${source_dir}"
install \
  -o root \
  -g root \
  -m 0644 \
  "${wheel_files[0]}" \
  "${release_dir}/$(basename -- "${wheel_files[0]}")"
install \
  -o root \
  -g root \
  -m 0644 \
  "${staging_dir}/requirements-edge.txt" \
  "${release_dir}/requirements-edge.txt"

if [[ ! -x "${release_dir}/.venv/bin/python" ]]; then
  python3 -m venv "${release_dir}/.venv"
fi
"${release_dir}/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --index-url https://mirrors.aliyun.com/pypi/simple/ \
  --requirement "${release_dir}/requirements-edge.txt"
"${release_dir}/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --index-url https://mirrors.aliyun.com/pypi/simple/ \
  --no-deps \
  --force-reinstall \
  "${release_dir}/$(basename -- "${wheel_files[0]}")"

operator_token_path="/etc/pawguide/operator.token"
if [[ ! -e "${operator_token_path}" ]]; then
  openssl rand -hex -out "${operator_token_path}" 32
fi
install \
  -o root \
  -g pawguide \
  -m 0640 \
  "${operator_token_path}" \
  "${operator_token_path}.installed"
mv -f "${operator_token_path}.installed" "${operator_token_path}"
install \
  -o root \
  -g pawguide \
  -m 0640 \
  "${staging_dir}/dev.token" \
  /etc/pawguide/dev.token
rm -f -- "${staging_dir}/dev.token"

tail_ip="$(tailscale ip -4 | head -n1)"
if [[ ! "${tail_ip}" =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Could not resolve a valid Tailscale IPv4 address." >&2
  exit 1
fi

env_tmp="$(mktemp /etc/pawguide/pawguide.env.XXXXXX)"
chmod 0640 "${env_tmp}"
chown root:pawguide "${env_tmp}"
{
  echo "PAWGUIDE_OPERATOR_TOKEN_FILE=/etc/pawguide/operator.token"
  echo "PAWGUIDE_DEV_TOKEN_FILE=/etc/pawguide/dev.token"
  echo "PAWGUIDE_WAYPOINTS=home,demo_a,demo_b"
  echo "PAWGUIDE_BIND_HOST=${tail_ip}"
  echo "PAWGUIDE_PORT=8765"
  echo "PAWGUIDE_ADAPTER=mock"
  echo "PAWGUIDE_ENABLE_REAL_MOTION=NO"
  echo "PAWGUIDE_DIMOS_MCP_URL=http://127.0.0.1:9990/mcp"
  echo "PAWGUIDE_ROBOT_CONNECTION=local_ap"
} >"${env_tmp}"
mv -f "${env_tmp}" /etc/pawguide/pawguide.env

install \
  -o root \
  -g root \
  -m 0644 \
  "${staging_dir}/pawguide-china-gateway.service" \
  /etc/systemd/system/pawguide-china-gateway.service

ln -sfn "${release_dir}" /opt/pawguide/current
ln -sfn "${source_dir}" /srv/pawguide/current
systemctl daemon-reload
systemctl enable pawguide-china-gateway.service
systemctl restart pawguide-china-gateway.service

for _attempt in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://${tail_ip}:8765/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS --max-time 5 "http://${tail_ip}:8765/health" >/dev/null
systemctl is-active --quiet pawguide-china-gateway.service

main_pid="$(systemctl show --property=MainPID --value pawguide-china-gateway.service)"
process_cwd="$(readlink -f "/proc/${main_pid}/cwd")"
if [[ "${process_cwd}" != "${release_dir}" ]]; then
  echo "Gateway process is using ${process_cwd:-unknown}, expected ${release_dir}." >&2
  exit 1
fi

listener="$(ss -H -lnt 'sport = :8765' | awk 'NR == 1 {print $4}')"
if [[ "${listener}" != "${tail_ip}:8765" ]]; then
  echo "Unexpected PawGuide listener: ${listener:-none}" >&2
  exit 1
fi

echo "PawGuide China development release ${release_id} is active."
echo "Gateway mode: mock (physical motion disabled)."
echo "Listener: ${tail_ip}:8765 (Tailscale only)."
