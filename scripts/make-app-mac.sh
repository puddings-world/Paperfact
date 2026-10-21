#!/usr/bin/env bash
# Create ~/Applications/Paperfact.app, a double-click launcher for the reader.
#
# The bundle only starts the venv's Python on `paper_daily app`; the code stays in
# this checkout, so a `git pull` updates the app without rebuilding the bundle.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
app="$HOME/Applications/Paperfact.app"

if [ ! -x "$root/.venv/bin/python" ]; then
  echo "the venv is missing -- run scripts/setup.sh first." >&2
  exit 1
fi

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

iconset="$(mktemp -d)/Paperfact.iconset"
"$root/.venv/bin/python" "$root/scripts/make_icon.py" --iconset "$iconset"
iconutil -c icns "$iconset" -o "$app/Contents/Resources/Paperfact.icns"
rm -rf "$(dirname "$iconset")"

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Paperfact</string>
  <key>CFBundleDisplayName</key><string>Paperfact</string>
  <key>CFBundleIdentifier</key><string>io.github.geniuspudding.paperfact</string>
  <key>CFBundleExecutable</key><string>Paperfact</string>
  <key>CFBundleIconFile</key><string>Paperfact</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Finder starts apps with a bare PATH, which would hide the claude CLI and any
# Homebrew tools the AI features call; keep the PATH this shell has.
cat > "$app/Contents/MacOS/Paperfact" <<LAUNCH
#!/bin/bash
export PATH="$PATH"
cd "$root"
exec "$root/.venv/bin/python" -m paper_daily app
LAUNCH
chmod +x "$app/Contents/MacOS/Paperfact"

echo "created $app -- drag it to the Dock to keep it there."
