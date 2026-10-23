#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Paperfact is not set up. Run bash scripts/setup.sh first." >&2
  exit 1
fi
exec .venv/bin/python -m paper_daily "$@"
