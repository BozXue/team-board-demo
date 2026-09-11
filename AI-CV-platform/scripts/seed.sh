#!/usr/bin/env bash
# Create the two demo projects (iPSC colony + synthetic surface defect).
# Safe to re-run: existing demo projects are reused.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/python" scripts/seed_demo.py "$@"
