#!/bin/bash
# Build Route-Mate for macOS using the existing, previously tested .icns icon.
# Run from the Route-Mate repository. Never modifies the source checkout except
# for ignored build/ and dist/ directories.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
PYTHON="${PYTHON:-python3}"
NAME="Route-Mate"
ICON="$ROOT/icon/RouteMate.icns"
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
# Resolve the already-built standalone renderer at BUILD time, not at app launch.
# Only the compiled renderer output is copied, not Karl's source checkout.
command -v git >/dev/null || { echo "ERROR: Git needed for build-time renderer preparation." >&2; exit 1; }
command -v node >/dev/null || { echo "ERROR: Node.js needed for build-time packaging." >&2; exit 1; }
RENDER_CLI="$("$PYTHON" -c 'from render.standalone_bridge import ensure_renderer; print(ensure_renderer())')"
# CLI lives under dist/standalone-renderer/; its parent modules live in dist/data,
# dist/components, dist/utils, and dist/types. Copy the entire compiled dist tree.
RENDER_DIST="$(dirname "$(dirname "$RENDER_CLI")")"
for required in \
  "standalone-renderer/cli.js" \
  "standalone-renderer/render.js" \
  "data/defaultComponents.js" \
  "components/stripboard/boardLayout.js" \
  "utils/resolveComponentDef.js"; do
  if [[ ! -f "$RENDER_DIST/$required" ]]; then
    echo "ERROR: Compiled renderer is missing $required" >&2
    exit 1
  fi
done
NODE_BIN="$(command -v node)"
RUNTIME="$ROOT/build/renderer-runtime"
mkdir -p "$RUNTIME"
rm -rf "$RUNTIME/dist"
ditto "$RENDER_DIST" "$RUNTIME/dist"
cp "$NODE_BIN" "$RUNTIME/node"
chmod +x "$RUNTIME/node"
"$RUNTIME/node" --version >/dev/null

# The frozen executable must initialize Python's multiprocessing spawn support.
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name "$NAME" \
  --icon "$ICON" \
  --paths "$ROOT" \
  --add-data "VERSION:." \
  --add-data "icon/RouteMate-original.png:icon" \
  --add-data "$RUNTIME/dist:renderer-runtime/dist" \
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
echo "Renderer and Node are included; runtime portability must still be checked."
echo "NOTE: First launch and actual solve must be verified on this Mac."
