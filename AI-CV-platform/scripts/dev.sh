#!/usr/bin/env bash
# Start backend (FastAPI) and frontend (Vite) for local development.
# Usage: scripts/dev.sh [backend_port] [frontend_port]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${1:-8002}"
FRONTEND_PORT="${2:-5174}"
PYTHON="$ROOT/.venv/bin/python"

export AICV_DATA_DIR="${AICV_DATA_DIR:-$ROOT/data}"

if [[ ! -x "$PYTHON" ]]; then
  echo "缺少虚拟环境，请先执行："
  echo "  python3 -m venv $ROOT/.venv && $ROOT/.venv/bin/pip install -r $ROOT/backend/requirements.txt"
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" && ! -d /opt/AI-CV-platform/frontend/node_modules ]]; then
  echo "缺少前端依赖，请先执行： cd $ROOT/frontend && npm install"
  exit 1
fi

cleanup() {
  echo
  echo "正在停止服务…"
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "数据目录 $AICV_DATA_DIR"
echo "后端 http://127.0.0.1:$BACKEND_PORT/docs"
echo "前端 http://127.0.0.1:$FRONTEND_PORT  （原平台仍是 5173，不要混用）"
(cd "$ROOT/backend" && "$ROOT/.venv/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT") &

if ! command -v node >/dev/null 2>&1; then
  for candidate in /home/gjq/.cursor-server/bin/linux-x64/*/node; do
    if [[ -x "$candidate" ]]; then
      export PATH="$(dirname "$candidate"):$PATH"
      break
    fi
  done
fi
SHARED_NM="/opt/AI-CV-platform/frontend/node_modules"
export NODE_PATH="${NODE_PATH:-$SHARED_NM}"
VITE_JS="$SHARED_NM/vite/bin/vite.js"
VITE_BIN="$ROOT/frontend/node_modules/.bin/vite"
if command -v npx >/dev/null 2>&1 && [[ -x "$VITE_BIN" ]]; then
  (cd "$ROOT/frontend" && AICV_BACKEND="http://127.0.0.1:$BACKEND_PORT" npx vite --host 0.0.0.0 --port "$FRONTEND_PORT") &
elif [[ -f "$VITE_JS" ]]; then
  (cd "$ROOT/frontend" && NODE_PATH="$SHARED_NM" AICV_BACKEND="http://127.0.0.1:$BACKEND_PORT" \
    node "$VITE_JS" --host 0.0.0.0 --port "$FRONTEND_PORT") &
elif [[ -x "$VITE_BIN" ]]; then
  (cd "$ROOT/frontend" && AICV_BACKEND="http://127.0.0.1:$BACKEND_PORT" "$VITE_BIN" --host 0.0.0.0 --port "$FRONTEND_PORT") &
else
  echo "找不到 node/npx，无法启动前端。"
  exit 1
fi

wait
