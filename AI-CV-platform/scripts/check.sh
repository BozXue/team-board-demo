#!/usr/bin/env bash
# End-to-end checks against a running backend:
#   1) API 契约（前端 types.ts 依赖的字段）
#   2) 全流程冒烟（建项目→导图→标注→调试→AI 规划→批量→发布→运行→训练→采图）
#   3) 前端类型检查 + 各路由首屏渲染 + jsdom 挂载（副作用、请求、重渲染循环）
# Usage: scripts/check.sh [base_url]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${1:-http://127.0.0.1:8000}"
cd "$ROOT/backend"

echo "== 接口契约检查 ($BASE)"
"$ROOT/.venv/bin/python" scripts/check_contracts.py "$BASE"

echo
echo "== 端到端冒烟（进程内 TestClient，不依赖上面的服务）"
"$ROOT/.venv/bin/python" scripts/smoke_api.py

echo
echo "== 前端类型检查"
cd "$ROOT/frontend" && npx tsc --noEmit && echo "tsc OK"

echo
echo "== 前端路由渲染检查 ($BASE)"
npx vite build --ssr scripts/render-check.tsx --outDir dist-ssr --logLevel warn
node dist-ssr/render-check.js "$BASE"

echo
echo "== 前端挂载与副作用检查（jsdom，可捕获重渲染死循环）"
npx vite build --ssr scripts/client-check.tsx --outDir dist-ssr --logLevel warn
node dist-ssr/client-check.js "$BASE"
