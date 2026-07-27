#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
node_binary=${IROS_NODE_BINARY:-$(command -v node)}

exec "$node_binary" \
  "$root_dir/apps/dashboard/node_modules/next/dist/bin/next" \
  build \
  --webpack
