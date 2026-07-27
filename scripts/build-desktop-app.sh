#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -f "$root_dir/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$root_dir/.env.local"
  set +a
fi

: "${IROS_SUPABASE_URL:?IROS_SUPABASE_URL is required}"
: "${IROS_SUPABASE_PUBLISHABLE_KEY:?IROS_SUPABASE_PUBLISHABLE_KEY is required}"

required_deno_version=2.9.3
actual_deno_version=$(deno --version | awk 'NR == 1 { print $2 }')
if [ "$actual_deno_version" != "$required_deno_version" ]; then
  echo "Desktop build requires Deno $required_deno_version; found $actual_deno_version" >&2
  exit 1
fi

"$root_dir/scripts/build-desktop-worker.sh"

DENO_DISABLE_NODE_SHIM=1
IROS_NODE_BINARY=$(command -v node)
export DENO_DISABLE_NODE_SHIM
export IROS_NODE_BINARY

desktop_attempt=1
while :; do
  rm -rf "$root_dir/node_modules" "$root_dir/apps/dashboard/node_modules"
  pnpm --dir "$root_dir" install --frozen-lockfile
  rm -rf "$root_dir/apps/dashboard/.next"
  cd "$root_dir/apps/dashboard"
  if deno desktop \
    --allow-all \
    --include npm:@swc/helpers@0.5.15 \
    --node-modules-dir=auto \
    --preload ./desktop/preload.ts \
    .
  then
    break
  fi
  if [ "$desktop_attempt" -ge 3 ]; then
    echo "Deno Desktop failed after $desktop_attempt attempts" >&2
    exit 1
  fi
  desktop_attempt=$((desktop_attempt + 1))
  echo "Retrying experimental Deno Desktop build ($desktop_attempt/3)" >&2
done

app_path="$root_dir/dist/Investment Research OS Preview.app"
plist_path="$app_path/Contents/Info.plist"
resources_dir="$app_path/Contents/Resources"
mkdir -p "$resources_dir"
cp "$root_dir/apps/dashboard/desktop/worker/iros-worker" "$resources_dir/iros-worker"
chmod 755 "$resources_dir/iros-worker"
/usr/libexec/PlistBuddy -c "Delete :NSAudioCaptureUsageDescription" "$plist_path"
/usr/libexec/PlistBuddy -c "Delete :NSBluetoothAlwaysUsageDescription" "$plist_path"
/usr/libexec/PlistBuddy -c "Delete :NSBluetoothPeripheralUsageDescription" "$plist_path"
/usr/libexec/PlistBuddy -c "Delete :NSCameraUsageDescription" "$plist_path"
/usr/libexec/PlistBuddy -c "Delete :NSMicrophoneUsageDescription" "$plist_path"
codesign --force --deep --sign - "$app_path"

rm -rf "$root_dir/node_modules" "$root_dir/apps/dashboard/node_modules"
pnpm --dir "$root_dir" install --frozen-lockfile
