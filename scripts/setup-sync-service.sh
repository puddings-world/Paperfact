#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
UV_PROJECT_ENVIRONMENT="$PWD/.venv-sync" uv sync --locked --python 3.11 --extra gcp
.venv-sync/bin/python -m paper_daily sync-admin upload-backup --help
echo "Ready: .venv-sync/bin/python -m paper_daily sync-admin --help"
echo "No authority, cloud login, upload, resource or service was created."
