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

for command_name in git uv; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "${command_name} is missing; run bootstrap-rdk-x5.sh first." >&2
    exit 1
  fi
done

bundle_dir="$(cd -- "${script_dir}/.." && pwd)"
patch_path="${bundle_dir}/vendor/dimos-pawguide.patch"
archive_path="${bundle_dir}/vendor/dimos-upstream.tar.gz"
source_dir="/opt/dimos-src"
venv_dir="/opt/dimos"
dimos_commit="4a78e1400c4334c280970e4610c655d16b9661ae"

if [[ ! -f "${patch_path}" ]]; then
  echo "Missing DimOS patch: ${patch_path}" >&2
  exit 1
fi

if [[ ! -e "${source_dir}" && -f "${archive_path}" ]]; then
  install -d -o root -g root -m 0755 "${source_dir}"
  tar -xzf "${archive_path}" -C "${source_dir}"
  printf '%s\n' "${dimos_commit}" > "${source_dir}/.pawguide-upstream-commit"
elif [[ ! -e "${source_dir}" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone \
    --filter=blob:none \
    https://github.com/dimensionalOS/dimos.git \
    "${source_dir}"
fi

if [[ -d "${source_dir}/.git" ]] &&
  [[ "$(git -C "${source_dir}" rev-parse HEAD)" != "${dimos_commit}" ]]; then
  if [[ -n "$(git -C "${source_dir}" status --porcelain)" ]]; then
    echo "${source_dir} has changes and is not at the pinned commit; refusing to overwrite it." >&2
    exit 1
  fi
  git -C "${source_dir}" fetch origin "${dimos_commit}"
  git -C "${source_dir}" checkout --detach "${dimos_commit}"
fi

if [[ -d "${source_dir}/.git" ]]; then
  if git -C "${source_dir}" apply --reverse --check "${patch_path}" >/dev/null 2>&1; then
    echo "PawGuide DimOS patch is already applied."
  elif git -C "${source_dir}" apply --check "${patch_path}"; then
    git -C "${source_dir}" apply "${patch_path}"
  else
    echo "DimOS source does not match the PawGuide patch." >&2
    exit 1
  fi
elif [[ ! -f "${source_dir}/.pawguide-upstream-commit" ]] ||
  [[ "$(<"${source_dir}/.pawguide-upstream-commit")" != "${dimos_commit}" ]]; then
  echo "Bundled DimOS source is not at the pinned commit." >&2
  exit 1
elif patch --directory="${source_dir}" --strip=1 --reverse --dry-run --silent \
  < "${patch_path}"; then
  echo "PawGuide DimOS patch is already applied."
elif patch --directory="${source_dir}" --strip=1 --dry-run --silent < "${patch_path}"; then
  patch --directory="${source_dir}" --strip=1 --silent < "${patch_path}"
else
  echo "DimOS source does not match the PawGuide patch." >&2
  exit 1
fi

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  uv venv --python 3.12 "${venv_dir}"
fi
# The default PyPI ARM resolver selects a multi-gigabyte CUDA 13 dependency
# stack. The X5 control path needs Torch only because DimOS imports its mapping
# abstractions, so install the official CPU wheel explicitly.
uv pip install \
  --python "${venv_dir}/bin/python" \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.13.0+cpu"
uv pip install \
  --python "${venv_dir}/bin/python" \
  --prerelease allow \
  --upgrade \
  --editable "${source_dir}[pawguide-edge]"

install -d -o root -g root -m 0755 /opt/pawguide/bin
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/run-dimos-x5.sh" \
  /opt/pawguide/bin/run-dimos-x5.sh
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/run-dimos-x5.sh" \
  /opt/pawguide/bin/run-dimos.sh
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/run-dimos-local-ap.py" \
  /opt/pawguide/bin/run-dimos-local-ap.py
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/direct-go2-mcp.py" \
  /opt/pawguide/bin/direct-go2-mcp.py
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/tag-waypoint.py" \
  /opt/pawguide/bin/tag-waypoint.py
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/diagnose-dimos-x5.sh" \
  /opt/pawguide/bin/diagnose-dimos-x5.sh
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/check-dimos-tools.py" \
  /opt/pawguide/bin/check-dimos-tools.py
for commissioning_script in \
  check-x5-readiness.sh \
  configure-go2-ap.sh \
  install-robot-credential.sh \
  rdk-x5-platform.sh \
  enable-real-motion.sh \
  disable-real-motion.sh; do
  install \
    -o root \
    -g root \
    -m 0755 \
    "${script_dir}/${commissioning_script}" \
    "/opt/pawguide/bin/${commissioning_script}"
done
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-dimos.service" \
  /etc/systemd/system/pawguide-dimos.service
install \
  -o root \
  -g root \
  -m 0755 \
  "${script_dir}/configure-lcm-network.sh" \
  /opt/pawguide/bin/configure-lcm-network.sh
install \
  -o root \
  -g root \
  -m 0644 \
  "${script_dir}/pawguide-lcm-network.service" \
  /etc/systemd/system/pawguide-lcm-network.service

printf 'x5\n' > /etc/pawguide/hardware-profile
chown root:pawguide /etc/pawguide/hardware-profile
chmod 0640 /etc/pawguide/hardware-profile
systemctl daemon-reload

echo
echo "Pinned PawGuide DimOS runtime installed for RDK X5."
echo "The physical service was not enabled and cannot start without its credential."
echo "After the hardware acceptance checks, run install-robot-credential.sh and enable-real-motion.sh."
