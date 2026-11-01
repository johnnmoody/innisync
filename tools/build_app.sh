#!/bin/bash
# Build /Applications/InniSync.app from this folder: builds the UI, copies the Python package into the bundle (so it
# runs without this folder), draws the icons, and runs it with the Python environment in ~/.venvs/innisync.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${INNISYNC_APP:-/Applications/InniSync.app}"
VENV="$HOME/.venvs/innisync"

[ -x "$VENV/bin/python" ] || { python3 -m venv "$VENV"; "$VENV/bin/pip" -q install -r "$SRC/requirements-dev.txt"; }

( cd "$SRC/ui" && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npx vite build --logLevel warn )

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
rsync -a --delete --exclude "__pycache__" "$SRC/innisync" "$SRC/run.py" "$APP/Contents/Resources/app/"

# icons: one per accent colour (the Dock icon follows it); the Finder icon uses the default
"$VENV/bin/python" "$SRC/tools/make_icons.py" "$APP/Contents/Resources/icons" >/dev/null
ICONSET=$(mktemp -d)/InniSync.iconset; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$APP/Contents/Resources/icons/black.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$APP/Contents/Resources/icons/black.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/InniSync.icns"

cat > "$APP/Contents/MacOS/InniSync" <<EOF
#!/bin/bash
exec "$VENV/bin/python" -I "\$(dirname "\$0")/../Resources/app/run.py" "\$@" >> "\$HOME/Library/Logs/InniSync.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/InniSync"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>InniSync</string>
  <key>CFBundleDisplayName</key><string>InniSync</string>
  <key>CFBundleIdentifier</key><string>io.github.johnnmoody.innisync</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>InniSync</string>
  <key>CFBundleIconFile</key><string>InniSync</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSLocalNetworkUsageDescription</key><string>InniSync reads your music from your Jellyfin or Subsonic server.</string>
</dict></plist>
EOF
echo "built $APP"
