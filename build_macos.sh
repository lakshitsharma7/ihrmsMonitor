#!/usr/bin/env bash
# Build a standalone native macOS .app bundle and distributable .dmg.
# Run this on macOS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================================="
echo "[1/4] Preparing Environment & Dependencies..."
echo "==================================================="
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt -r requirements-macos.txt

echo ""
echo "==================================================="
echo "[2/4] Running Automated Tests..."
echo "==================================================="
export QT_QPA_PLATFORM=offscreen
python3 -m unittest discover tests

echo ""
echo "==================================================="
echo "[3/4] Building Workpulse.app with PyInstaller..."
echo "==================================================="
pyinstaller --noconfirm --clean Workpulse-macos.spec

if [ ! -d "dist/Workpulse.app" ]; then
    echo "ERROR: dist/Workpulse.app was not generated!" >&2
    exit 1
fi

echo "App bundle created successfully at dist/Workpulse.app"

echo ""
echo "==================================================="
echo "[4/4] Creating Distributable Workpulse.dmg..."
echo "==================================================="
DMG_STAGING="dist/dmg_staging"
rm -rf "$DMG_STAGING" "dist/Workpulse.dmg"
mkdir -p "$DMG_STAGING"

cp -R "dist/Workpulse.app" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

# Copy Volume Icon if available
if [ -f "assets/ihrms-logo-icon.icns" ]; then
    cp "assets/ihrms-logo-icon.icns" "$DMG_STAGING/.VolumeIcon.icns" || true
fi

hdiutil create \
    -volname "Workpulse" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    "dist/Workpulse.dmg"

rm -rf "$DMG_STAGING"

if [ ! -f "dist/Workpulse.dmg" ]; then
    echo "ERROR: dist/Workpulse.dmg was not generated!" >&2
    exit 1
fi

echo ""
echo "==================================================="
echo "macOS Build Complete:"
echo "  1. dist/Workpulse.app"
echo "  2. dist/Workpulse.dmg ($(du -h dist/Workpulse.dmg | cut -f1))"
echo "==================================================="
