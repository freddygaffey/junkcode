#!/usr/bin/env bash
# Build Lyrebird.app and a distributable .dmg.
#   ./build/build-macos.sh            build .app + .dmg
#   ./build/build-macos.sh --app-only skip the dmg
set -euo pipefail

export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export APP_NAME="${APP_NAME:-Lyrebird}"
VENV="$PROJECT_ROOT/.venv"
DIST="$PROJECT_ROOT/dist"
APP="$DIST/$APP_NAME.app"
DMG="$DIST/$APP_NAME.dmg"
APP_ONLY=0
[ "${1:-}" = "--app-only" ] && APP_ONLY=1

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ -d "$VENV" ] || { echo "Run ./setup.sh first"; exit 1; }

say "Building $APP_NAME.app"
rm -rf "$DIST" "$PROJECT_ROOT/build/work"
"$VENV/bin/pyinstaller" \
  --noconfirm --clean \
  --distpath "$DIST" \
  --workpath "$PROJECT_ROOT/build/work" \
  "$PROJECT_ROOT/build/app.spec"

[ -d "$APP" ] || { echo "Build failed: $APP not produced"; exit 1; }
say "Built $(du -sh "$APP" | cut -f1) at $APP"

# Ad-hoc signature. Without this, Gatekeeper kills the app on launch with a
# generic "damaged" error that tells the user nothing useful.
say "Signing (ad-hoc)"
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "  (codesign skipped)"

if [ "$APP_ONLY" -eq 1 ]; then echo; echo "Done: $APP"; exit 0; fi

say "Creating $APP_NAME.dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/READ ME FIRST.txt" <<TXT
$APP_NAME — offline dictation

1. Drag $APP_NAME to the Applications folder.
2. Open it. macOS will ask for Microphone and Accessibility permission —
   both are required, and both are why it can type for you.
3. The settings window opens automatically. Press F5 to start dictating.

The first launch downloads the speech model (about 1.6 GB) and will take a
few minutes. After that everything runs offline. Nothing you say is uploaded.

If macOS says the app "cannot be opened because the developer cannot be
verified": right-click the app and choose Open, then confirm. That happens
because this is not signed with a paid Apple Developer certificate.
TXT
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

say "Done"
echo "  App: $APP"
echo "  DMG: $DMG  ($(du -sh "$DMG" | cut -f1))"
