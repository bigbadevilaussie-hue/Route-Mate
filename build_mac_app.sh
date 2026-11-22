#!/bin/bash
# Build Route-Mate for macOS on the target Mac, using its existing icon.
# Run from the Route-Mate repository. Never modifies the source checkout except
# for ignored build/ and dist/ directories.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
PYTHON="${PYTHON:-python3}"
NAME="Route-Mate"
ICON="$ROOT/icon/RouteMate-original.png"
ICONS="$ROOT/build/mac-icon"
APP="$ROOT/dist/$NAME.app"
DEST="$HOME/Desktop/$NAME.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: Build on macOS (the target Intel iMac)." >&2
  exit 1
fi
if [[ ! -f "$ICON" ]]; then
  echo "ERROR: Missing icon: $ICON" >&2
  exit 1
fi
if [[ -e "$DEST" ]]; then
  echo "ERROR: Desktop already has $DEST. Move it aside first; nothing overwritten." >&2
  exit 1
fi
"$PYTHON" -m PyInstaller --version >/dev/null 2>&1 || {
  echo "ERROR: PyInstaller missing. Install it: $PYTHON -m pip install pyinstaller" >&2
  exit 1
}
"$PYTHON" -c "import PySide6" || {
  echo "ERROR: PySide6 missing. Install: $PYTHON -m pip install -r requirements-gui.txt" >&2
  exit 1
}
command -v sips >/dev/null
command -v iconutil >/dev/null

mkdir -p "$ICONS.iconset"
for entry in "16 16x16" "32 16x16@2x" "32 32x32" "64 32x32@2x" "128 128x128" "256 128x128@2x" "256 256x256" "512 256x256@2x" "512 512x512" "1024 512x512@2x"; do
  read -r px name <<<"$entry"
  sips -s format png -z "$px" "$px" "$ICON" --out "$ICONS.iconset/icon_$name.png" >/dev/null
done
iconutil -c icns "$ICONS.iconset" -o "$ICONS.icns"

# Resolve the already-built standalone renderer at BUILD time, not at app launch.
# Only the compiled renderer output is copied, not Karl's source checkout.
command -v git >/dev/null || { echo "ERROR: Git needed for build-time renderer preparation." >&2; exit 1; }
command -v node >/dev/null || { echo "ERROR: Node.js needed for build-time packaging." >&2; exit 1; }
RENDER_CLI="$("$PYTHON" -c 'from render.standalone_bridge import ensure_renderer; print(ensure_renderer())')"
RENDER_DIR="$(dirname "$RENDER_CLI")"
NODE_BIN="$(command -v node)"
RUNTIME="$ROOT/build/renderer-runtime"
mkdir -p "$RUNTIME"
rm -rf "$RUNTIME/standalone-renderer"
ditto "$RENDER_DIR" "$RUNTIME/standalone-renderer"
cp "$NODE_BIN" "$RUNTIME/node"
chmod +x "$RUNTIME/node"
"$RUNTIME/node" --version >/dev/null

# The frozen executable must initialize Python's multiprocessing spawn support.
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name "$NAME" \
  --icon "$ICONS.icns" \
  --add-data "VERSION:." \
  --add-data "icon/RouteMate-original.png:icon" \
  --add-data "$RUNTIME/standalone-renderer:renderer-runtime/standalone-renderer" \
  --add-binary "$RUNTIME/node:renderer-runtime" \
  --collect-submodules solve \
  --collect-submodules pipeline \
  run_gui.py

if [[ ! -d "$APP/Contents/MacOS" ]]; then
  echo "ERROR: PyInstaller did not create expected app bundle $APP" >&2
  exit 1
fi
ditto "$APP" "$DEST"
echo
echo "BUILT: $DEST"
echo "Double-click Route-Mate.app on your Desktop."
echo "Bundled standalone renderer and Node; no system Git/Node needed at runtime."
echo "NOTE: First launch and actual solve must be verified on this Mac."
