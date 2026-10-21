#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# A run cut off while creating it leaves a .venv with no Python, which uv then
# refuses to reuse; recreate it in that case, and keep a working one as it is.
[ -x .venv/bin/python ] || uv venv --clear --python 3.11
echo "Installing dependencies (the desktop reader pulls ~1 GB of Qt; this takes a few minutes)..."
uv sync --extra dev --extra app
echo "AI profiles can be configured in the reader with AI settings; see docs/architecture.md."
mkdir -p data
.venv/bin/python -m paper_daily fonts
.venv/bin/python -m paper_daily web-assets
.venv/bin/python scripts/make_icon.py

echo
echo "Open AI settings in the app to install/sign in to Claude, Codex or Gemini."
echo "Choose your account and model there; API configuration is optional."
echo "A fresh workspace starts empty. Create a list or import a colleague's research bundle."
echo "Importing research bundles and reading saved work need no AI account."

echo
echo "Done. Next:"
echo "  ./scripts/dev.sh app    # open Paperfact, add your papers and configure AI settings"
echo "  ./scripts/dev.sh doctor # check the installation if needed"
echo "  Optional ML conference workflow: see docs/ml-daily.md."
if [ "$(uname)" = "Darwin" ]; then
  echo "  ./scripts/make-app-mac.sh                       # Paperfact.app in ~/Applications"
fi
