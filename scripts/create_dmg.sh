#!/usr/bin/env bash
# Standalone DMG creation script for Workpulse macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

APP_BUNDLE="${1:-dist/Workpulse.app}"
DMG_FILE="${2:-dist/macOS/Workpulse.dmg}"
DMG_STAGING="dist/dmg_staging"

if [ ! -d "${APP_BUNDLE}" ]; then
    echo "ERROR: App bundle not found at ${APP_BUNDLE}" >&2
    exit 1
fi

mkdir -p "$(dirname "${DMG_FILE}")"

echo "==================================================="
echo "Creating Workpulse macOS DMG from ${APP_BUNDLE}"
echo "==================================================="

rm -rf "${DMG_STAGING}" "${DMG_FILE}"
mkdir -p "${DMG_STAGING}"

# Copy application bundle to staging directory
cp -R "${APP_BUNDLE}" "${DMG_STAGING}/"

# Add link to Applications folder
ln -s /Applications "${DMG_STAGING}/Applications"

# Add Volume Icon if present
if [ -f "assets/ihrms-logo-icon.icns" ]; then
    cp "assets/ihrms-logo-icon.icns" "${DMG_STAGING}/.VolumeIcon.icns" 2>/dev/null || true
fi

# Create compressed UDZO disk image
hdiutil create \
    -volname "Workpulse" \
    -srcfolder "${DMG_STAGING}" \
    -ov \
    -format UDZO \
    "${DMG_FILE}"

rm -rf "${DMG_STAGING}"

if [ ! -f "${DMG_FILE}" ]; then
    echo "ERROR: DMG creation failed! File not found at ${DMG_FILE}" >&2
    exit 1
fi

echo "==================================================="
echo "DMG created successfully at: ${DMG_FILE}"
echo "Size: $(du -h "${DMG_FILE}" | cut -f1)"
echo "==================================================="
