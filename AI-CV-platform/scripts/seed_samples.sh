#!/usr/bin/env bash
# Import every folder under sample_projects/ as a platform project.
# Safe to re-run: existing projects with the same name are reused.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AICV_DATA_DIR="${AICV_DATA_DIR:-$ROOT/data}"
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/python" -m scripts.seed_sample_projects "$@"
