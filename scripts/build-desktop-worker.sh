#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${PYTHON_BIN:-"$root_dir/.venv/bin/python"}
PYINSTALLER_CONFIG_DIR="$root_dir/build/pyinstaller-cache"
export PYINSTALLER_CONFIG_DIR

if [ ! -x "$python_bin" ]; then
  echo "Desktop build requires $python_bin" >&2
  exit 1
fi

if ! "$python_bin" -m PyInstaller --version >/dev/null 2>&1; then
  echo "Install desktop build tools: $python_bin -m pip install -e '$root_dir[desktop-build]'" >&2
  exit 1
fi

"$python_bin" -m PyInstaller \
  --clean \
  --distpath "$root_dir/apps/dashboard/desktop/worker" \
  --name iros-worker \
  --noconfirm \
  --onefile \
  --specpath "$root_dir/build/desktop-worker" \
  --workpath "$root_dir/build/desktop-worker" \
  "$root_dir/workers/desktop/__main__.py"

expected_status='{"contract_version":"desktop_worker_status.v1","state":"ready","worker_id":"iros-desktop-worker"}'
actual_status=$("$root_dir/apps/dashboard/desktop/worker/iros-worker" --healthcheck)
if [ "$actual_status" != "$expected_status" ]; then
  echo "Packaged desktop worker failed readiness contract" >&2
  exit 1
fi
