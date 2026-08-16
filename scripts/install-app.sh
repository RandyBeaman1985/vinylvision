#!/bin/zsh
# Build VinylVision.app into /Applications, pointing at this checkout's venv.
# Re-run any time; it rebuilds the bundle in place.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="/Applications/VinylVision.app"

if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "No .venv found — run: uv venv --python 3.12 && uv pip install -r requirements.txt" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>VinylVision</string>
  <key>CFBundleDisplayName</key><string>VinylVision</string>
  <key>CFBundleIdentifier</key><string>com.cleverfoxailabs.vinylvision</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>VinylVision</string>
  <key>CFBundleIconFile</key><string>VinylVision</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>VinylVision listens to your record player so it can identify the song and sync its music video.</string>
</dict>
</plist>
PLIST

# LaunchServices refuses script executables in bundles on modern macOS,
# so compile a tiny native launcher that execs the venv python.
LAUNCHER_SRC="$(mktemp -t vvlauncher).c"
cat > "$LAUNCHER_SRC" <<EOF
#include <stdlib.h>
#include <unistd.h>
int main(void) {
    setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    chdir("$REPO");   /* python -m needs the package dir on sys.path */
    const char *py = "$REPO/.venv/bin/python";
    execl(py, py, "-m", "vinylvision.app", (char *)NULL);
    return 1;
}
EOF
cc -O2 -o "$APP/Contents/MacOS/VinylVision" "$LAUNCHER_SRC"
rm -f "$LAUNCHER_SRC"

cp "$REPO/assets/VinylVision.icns" "$APP/Contents/Resources/VinylVision.icns"
cp "$REPO/assets/icon-src.png" "$APP/Contents/Resources/icon.png"

codesign --force --deep -s - "$APP" 2>/dev/null || true
touch "$APP"   # nudge LaunchServices/Finder to pick up the icon

echo "Installed $APP"
echo "First launch: approve the microphone prompt. Drag it to the Dock and you're done."
