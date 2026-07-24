#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
uv_bin="${UV_BIN:-uv}"
dimos_source_dir="${DIMOS_SOURCE_DIR:-/root/dimos}"
dimos_commit="4a78e1400c4334c280970e4610c655d16b9661ae"
hardware_target="${1:-x5}"
case "${hardware_target}" in
  x5 | s100) ;;
  *)
    echo "Usage: $0 [x5|s100]" >&2
    exit 2
    ;;
esac
bundle_name="pawguide-${hardware_target}-mvp"

cd "${project_dir}"
if [[ "$(git -C "${dimos_source_dir}" rev-parse HEAD)" != "${dimos_commit}" ]]; then
  echo "DimOS source is not at the pinned PawGuide commit." >&2
  exit 1
fi
GIT_LFS_SKIP_SMUDGE=1 git -C "${dimos_source_dir}" archive \
  --format=tar.gz \
  --output="${project_dir}/vendor/dimos-upstream.tar.gz" \
  "${dimos_commit}"

"${uv_bin}" run --extra dev pytest
"${uv_bin}" build --wheel --out-dir dist
"${uv_bin}" export \
  --locked \
  --no-dev \
  --no-emit-project \
  --no-hashes \
  --output-file dist/requirements-edge.txt
PYTHONPATH=src "${uv_bin}" run python provision/export-openapi.py

staging_dir="$(mktemp -d)"
trap 'rm -rf -- "${staging_dir}"' EXIT
install -d "${staging_dir}/${bundle_name}/dist"
cp dist/pawguide-*.whl "${staging_dir}/${bundle_name}/dist/"
cp dist/requirements-edge.txt "${staging_dir}/${bundle_name}/dist/"
cp -R config contracts docs pixel provision vendor README.md \
  "${staging_dir}/${bundle_name}/"

(
  cd "${staging_dir}/${bundle_name}"
  find . -type f ! -name SHA256SUMS -print0 |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
)

tar \
  -C "${staging_dir}" \
  -czf "${project_dir}/dist/${bundle_name}.tar.gz" \
  "${bundle_name}"
sha256sum "${project_dir}/dist/${bundle_name}.tar.gz"
