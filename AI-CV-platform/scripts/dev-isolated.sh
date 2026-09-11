#!/usr/bin/env bash
# Isolated copy: frontend 5174, backend 8002, own data directory.
# Original platform on 5173/8000 is not touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AICV_DATA_DIR="${AICV_DATA_DIR:-$ROOT/data}"
echo "数据目录 $AICV_DATA_DIR"
echo "打开 http://<本机IP>:5174  （不要再用 5173）"
exec "$ROOT/scripts/dev.sh" 8002 5174
