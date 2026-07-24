#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
china_host="${PAWGUIDE_CHINA_HOST:-120.55.44.117}"
china_port="${PAWGUIDE_CHINA_SSH_PORT:-28796}"
china_identity="${PAWGUIDE_CHINA_IDENTITY:-/root/.ssh/id_ed25519}"
local_token_file="${PAWGUIDE_CHINA_DEV_TOKEN_FILE:-/etc/pawguide/china-dev.token}"

for command_name in "${uv_bin}" ssh scp openssl sha256sum tar; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done
if [[ ! -f "${china_identity}" ]]; then
  echo "SSH identity does not exist: ${china_identity}" >&2
  exit 1
fi

ssh_options=(
  -p "${china_port}"
  -i "${china_identity}"
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
)
scp_options=(
  -P "${china_port}"
  -i "${china_identity}"
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
)

cd "${project_dir}"
"${uv_bin}" run --extra dev pytest
"${uv_bin}" build --wheel --out-dir dist
"${uv_bin}" export \
  --locked \
  --no-dev \
  --no-emit-project \
  --no-hashes \
  --output-file dist/requirements-edge.txt

wheel_files=("${project_dir}"/dist/pawguide-*.whl)
if [[ "${#wheel_files[@]}" -ne 1 || ! -f "${wheel_files[0]}" ]]; then
  echo "Expected exactly one PawGuide wheel under ${project_dir}/dist." >&2
  exit 1
fi

local_token_dir="$(dirname -- "${local_token_file}")"
if [[ ! -d "${local_token_dir}" ]]; then
  install -d -o root -g root -m 0700 "${local_token_dir}"
fi
if [[ ! -e "${local_token_file}" ]]; then
  openssl rand -hex -out "${local_token_file}" 32
fi
chmod 0600 "${local_token_file}"
if ! grep -Eq '^[0-9a-f]{64}$' "${local_token_file}"; then
  echo "The local China development token has an invalid format." >&2
  exit 1
fi

staging_dir="$(mktemp -d)"
remote_staging=""
cleanup() {
  rm -rf -- "${staging_dir}"
  if [[ -n "${remote_staging}" ]]; then
    ssh "${ssh_options[@]}" "root@${china_host}" \
      "if [[ '${remote_staging}' =~ ^/root/pawguide-deploy-[0-9a-f]{12}\$ ]] && [[ -d '${remote_staging}' ]]; then find '${remote_staging}' -mindepth 1 -maxdepth 1 -type f -delete; rmdir '${remote_staging}'; fi" \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
source_archive="${staging_dir}/pawguide-source.tar.gz"
tar \
  -C "${project_dir}" \
  -czf "${source_archive}" \
  README.md \
  pyproject.toml \
  uv.lock \
  config \
  contracts \
  docs \
  pixel \
  provision \
  src \
  tests

cp "${wheel_files[0]}" "${staging_dir}/"
cp dist/requirements-edge.txt "${staging_dir}/"
cp provision/install-china-dev.sh "${staging_dir}/"
cp provision/pawguide-china-gateway.service "${staging_dir}/"
cp provision/pawguide-china-resolved.conf "${staging_dir}/"
cp "${local_token_file}" "${staging_dir}/dev.token"
chmod 0600 "${staging_dir}/dev.token"

release_id="$(
  (
    cd "${staging_dir}"
    sha256sum \
      pawguide-*.whl \
      requirements-edge.txt \
      pawguide-source.tar.gz \
      pawguide-china-gateway.service \
      pawguide-china-resolved.conf
  ) | sha256sum | cut -c1-12
)"
remote_staging="/root/pawguide-deploy-${release_id}"

(
  cd "${staging_dir}"
  sha256sum \
    pawguide-*.whl \
    requirements-edge.txt \
    pawguide-source.tar.gz \
    pawguide-china-gateway.service \
    pawguide-china-resolved.conf \
    dev.token >SHA256SUMS
)

ssh "${ssh_options[@]}" "root@${china_host}" \
  "install -d -o root -g root -m 0700 '${remote_staging}'"
scp "${scp_options[@]}" \
  "${staging_dir}/SHA256SUMS" \
  "${staging_dir}/dev.token" \
  "${staging_dir}/install-china-dev.sh" \
  "${staging_dir}/pawguide-china-gateway.service" \
  "${staging_dir}/pawguide-china-resolved.conf" \
  "${staging_dir}/pawguide-source.tar.gz" \
  "${staging_dir}/requirements-edge.txt" \
  "${wheel_files[0]}" \
  "root@${china_host}:${remote_staging}/"

ssh "${ssh_options[@]}" "root@${china_host}" \
  "bash '${remote_staging}/install-china-dev.sh' '${release_id}' '${remote_staging}'"

echo "China deployment completed: ${release_id}"
