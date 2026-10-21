#!/usr/bin/env bash
# Build, sign, notarize, staple, and package a standalone native macOS iHRMS Desktop application and DMG.
# Run this script on macOS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENTITLEMENTS_FILE="entitlements.mac.plist"
APP_BUNDLE="dist/iHRMS-Desktop.app"
DMG_STAGING="dist/dmg_staging"

APP_VER="1.0.0"
if [ -f "VERSION" ]; then
    APP_VER="$(tr -d '[:space:]' < VERSION)"
fi
DMG_FILE="dist/macOS/iHRMS-Desktop-${APP_VER}.dmg"

echo "==================================================="
echo "[1/6] Preparing Environment & Cleaning Stale Builds (v${APP_VER})"
echo "==================================================="
mkdir -p "dist/macOS"
rm -rf build/ dist/Workpulse.app "dist/iHRMS-Desktop.app" "dist/iHRMS Desktop.app" "${DMG_STAGING}" "dist/macOS"/*
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt -r requirements-macos.txt

if [ "${SKIP_TESTS:-0}" != "1" ]; then
    echo ""
    echo "==================================================="
    echo "[2/6] Running Automated Tests..."
    echo "==================================================="
    export QT_QPA_PLATFORM=offscreen
    python3 scripts/run_tests.py
fi

echo ""
echo "==================================================="
echo "[3/6] Building iHRMS-Desktop.app from current source..."
echo "==================================================="
pyinstaller --noconfirm --clean iHRMS-Desktop-macos.spec

if [ ! -d "${APP_BUNDLE}" ]; then
    echo "ERROR: ${APP_BUNDLE} was not generated!" >&2
    exit 1
fi

if [ ! -f "${APP_BUNDLE}/Contents/MacOS/iHRMS-Desktop" ]; then
    echo "ERROR: Main executable ${APP_BUNDLE}/Contents/MacOS/iHRMS-Desktop missing!" >&2
    exit 1
fi

if [ ! -f "${APP_BUNDLE}/Contents/Info.plist" ]; then
    echo "ERROR: Info.plist not found in ${APP_BUNDLE}/Contents/!" >&2
    exit 1
fi

# Verify version in Info.plist
PLIST_VER="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${APP_BUNDLE}/Contents/Info.plist" 2>/dev/null || true)"
echo "Verified Info.plist version: ${PLIST_VER}"

echo "Newly built application bundle verified at ${APP_BUNDLE}"

echo ""
echo "==================================================="
echo "[4/6] Code Signing iHRMS-Desktop.app (Inside-Out with Hardened Runtime)..."
echo "==================================================="

# Discover Signing Identity
SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [ -z "${SIGNING_IDENTITY}" ]; then
    # Auto-detect Developer ID Application certificate from macOS keychain
    DETECTED_ID="$(security find-identity -v -p codesigning 2>/dev/null | grep "Developer ID Application:" | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/' || true)"
    if [ -n "${DETECTED_ID}" ]; then
        SIGNING_IDENTITY="${DETECTED_ID}"
        echo "Auto-detected Developer ID Application identity from keychain: ${SIGNING_IDENTITY}"
    fi
fi

if [ -n "${SIGNING_IDENTITY}" ]; then
    echo "Signing identity: ${SIGNING_IDENTITY}"

    if [ ! -f "${ENTITLEMENTS_FILE}" ]; then
        echo "ERROR: Entitlements file ${ENTITLEMENTS_FILE} not found!" >&2
        exit 1
    fi

    # Clean any extended attributes or DS_Store before signing
    find "${APP_BUNDLE}" -name ".DS_Store" -delete 2>/dev/null || true
    xattr -cr "${APP_BUNDLE}" 2>/dev/null || true

    echo "--> [4a] Signing embedded libraries (.dylib, .so)..."
    find "${APP_BUNDLE}/Contents" -type f \( -name "*.dylib" -o -name "*.so" \) | while read -r lib; do
        codesign --force --timestamp --options runtime --sign "${SIGNING_IDENTITY}" "${lib}"
    done

    echo "--> [4b] Signing embedded frameworks and helpers..."
    if [ -d "${APP_BUNDLE}/Contents/Frameworks" ]; then
        for fw in "${APP_BUNDLE}/Contents/Frameworks"/*.framework; do
            if [ -d "${fw}" ]; then
                codesign --force --timestamp --options runtime --sign "${SIGNING_IDENTITY}" "${fw}"
            fi
        done
    fi

    # Sign any nested Mach-O helper executables inside Contents/MacOS (excluding main binary)
    find "${APP_BUNDLE}/Contents/MacOS" -type f ! -name "iHRMS-Desktop" | while read -r helper; do
        if file "${helper}" 2>/dev/null | grep -q "Mach-O"; then
            codesign --force --timestamp --options runtime \
                --entitlements "${ENTITLEMENTS_FILE}" \
                --sign "${SIGNING_IDENTITY}" \
                "${helper}"
        fi
    done

    echo "--> [4c] Signing main executable with Hardened Runtime & Entitlements..."
    codesign --force --timestamp --options runtime \
        --entitlements "${ENTITLEMENTS_FILE}" \
        --sign "${SIGNING_IDENTITY}" \
        "${APP_BUNDLE}/Contents/MacOS/iHRMS-Desktop"

    echo "--> [4d] Signing top-level application bundle..."
    codesign --force --timestamp --options runtime \
        --entitlements "${ENTITLEMENTS_FILE}" \
        --sign "${SIGNING_IDENTITY}" \
        "${APP_BUNDLE}"

    echo ""
    echo "--> [4e] Verifying code signature..."
    codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"
    codesign --display --verbose=4 "${APP_BUNDLE}"
    echo "Code signature verified successfully."
else
    echo "WARNING: No Apple Developer ID Application signing identity provided."
    echo "Set APPLE_SIGNING_IDENTITY or import Developer ID certificate to sign for production."
    if [ "${REQUIRE_SIGNING:-0}" = "1" ]; then
        echo "ERROR: Production release requires valid Apple Developer ID Application certificate!" >&2
        exit 1
    fi
fi

echo ""
echo "==================================================="
echo "[5/6] Creating & Verifying iHRMS-Desktop-${APP_VER}.dmg..."
echo "==================================================="
rm -rf "${DMG_STAGING}" "${DMG_FILE}"
mkdir -p "${DMG_STAGING}"

cp -R "${APP_BUNDLE}" "${DMG_STAGING}/"
ln -s /Applications "${DMG_STAGING}/Applications"

if [ -f "assets/ihrms-logo-icon.icns" ]; then
    cp "assets/ihrms-logo-icon.icns" "${DMG_STAGING}/.VolumeIcon.icns" 2>/dev/null || true
fi

hdiutil create \
    -volname "iHRMS-Desktop" \
    -srcfolder "${DMG_STAGING}" \
    -ov \
    -format UDZO \
    "${DMG_FILE}"

rm -rf "${DMG_STAGING}"

if [ ! -f "${DMG_FILE}" ]; then
    echo "ERROR: ${DMG_FILE} was not generated!" >&2
    exit 1
fi

if [ -n "${SIGNING_IDENTITY}" ]; then
    echo "Signing DMG file with Developer ID..."
    codesign --force --timestamp --sign "${SIGNING_IDENTITY}" "${DMG_FILE}"
    codesign --verify --verbose=2 "${DMG_FILE}"
fi

echo "DMG created at ${DMG_FILE} ($(du -h "${DMG_FILE}" | cut -f1))"

# Test mounting the newly created DMG and verify payload
echo "Verifying DMG mount and installation structure..."
MOUNT_DIR="$(mktemp -d /tmp/ihrms_dmg_mount.XXXXXX)"
hdiutil attach "${DMG_FILE}" -mountpoint "${MOUNT_DIR}" -nobrowse -readonly

if [ ! -d "${MOUNT_DIR}/iHRMS-Desktop.app" ]; then
    echo "ERROR: iHRMS-Desktop.app not present inside mounted DMG!" >&2
    hdiutil detach "${MOUNT_DIR}" || true
    rm -rf "${MOUNT_DIR}"
    exit 1
fi

MOUNTED_VER="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${MOUNT_DIR}/iHRMS-Desktop.app/Contents/Info.plist" 2>/dev/null || true)"
echo "Verified version inside mounted DMG: ${MOUNTED_VER}"

hdiutil detach "${MOUNT_DIR}"
rm -rf "${MOUNT_DIR}"
echo "DMG mount test passed cleanly."

echo ""
echo "==================================================="
echo "[6/6] Apple Notarization & Stapling..."
echo "==================================================="

NOTARY_ARGS=()
TEMP_KEY_FILE=""

# Check for API Key credentials
if [ -n "${APPLE_API_KEY_BASE64:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ]; then
    TEMP_KEY_FILE="$(mktemp /tmp/AuthKey_XXXXXX.p8)"
    echo "${APPLE_API_KEY_BASE64}" | base64 --decode > "${TEMP_KEY_FILE}"
    NOTARY_ARGS=(
        "--key" "${TEMP_KEY_FILE}"
        "--key-id" "${APPLE_API_KEY_ID}"
        "--issuer" "${APPLE_API_ISSUER}"
    )
elif [ -n "${APPLE_API_KEY_PATH:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ]; then
    NOTARY_ARGS=(
        "--key" "${APPLE_API_KEY_PATH}"
        "--key-id" "${APPLE_API_KEY_ID}"
        "--issuer" "${APPLE_API_ISSUER}"
    )
# Check for Apple ID + App-Specific Password
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    NOTARY_ARGS=(
        "--apple-id" "${APPLE_ID}"
        "--password" "${APPLE_APP_SPECIFIC_PASSWORD}"
        "--team-id" "${APPLE_TEAM_ID}"
    )
# Check for stored Keychain profile
elif [ -n "${APPLE_KEYCHAIN_PROFILE:-}" ]; then
    NOTARY_ARGS=(
        "--keychain-profile" "${APPLE_KEYCHAIN_PROFILE}"
    )
fi

cleanup_notary() {
    if [ -n "${TEMP_KEY_FILE}" ] && [ -f "${TEMP_KEY_FILE}" ]; then
        rm -f "${TEMP_KEY_FILE}"
    fi
}
trap cleanup_notary EXIT

if [ ${#NOTARY_ARGS[@]} -gt 0 ]; then
    echo "Submitting ${DMG_FILE} to Apple Notary Service via xcrun notarytool..."
    
    # Run notarytool submit and capture output
    set +e
    NOTARY_SUBMISSION=$(xcrun notarytool submit "${DMG_FILE}" "${NOTARY_ARGS[@]}" --wait 2>&1)
    NOTARY_EXIT_CODE=$?
    set -e

    echo "${NOTARY_SUBMISSION}"

    # Extract Submission ID
    SUBMISSION_ID=$(echo "${NOTARY_SUBMISSION}" | grep -E "^\s*id:" | head -n 1 | awk '{print $2}' || true)
    
    if [ ${NOTARY_EXIT_CODE} -ne 0 ] || echo "${NOTARY_SUBMISSION}" | grep -qi "status: Invalid"; then
        echo ""
        echo "==================================================="
        echo "ERROR: Apple Notarization Failed!"
        echo "==================================================="
        if [ -n "${SUBMISSION_ID}" ]; then
            echo "Fetching Apple Notarization Log for Submission ID: ${SUBMISSION_ID}..."
            xcrun notarytool log "${SUBMISSION_ID}" "${NOTARY_ARGS[@]}" || true
        fi
        exit 1
    fi

    echo ""
    echo "Apple Notarization Accepted! Stapling ticket to DMGs and App bundle..."
    xcrun stapler staple "${APP_BUNDLE}" || true
    xcrun stapler staple "${DMG_FILE}"
    xcrun stapler validate "${DMG_FILE}"
    echo "Ticket successfully stapled and validated."

    # Assess the app with spctl Gatekeeper
    if command -v spctl >/dev/null 2>&1; then
        echo ""
        echo "Running Gatekeeper assessment (spctl)..."
        spctl --assess --type execute --verbose=4 "${APP_BUNDLE}"
        spctl --assess --type install --verbose=4 "${DMG_FILE}"
        echo "Gatekeeper assessments passed successfully: accepted as recognized developer application."
    fi
else
    echo "Notice: Apple Notarization credentials not configured. Skipping notarytool."
    echo "To notarize, supply APPLE_API_KEY_BASE64/ID/ISSUER or APPLE_ID/PASSWORD/TEAM_ID."
    if [ "${REQUIRE_NOTARIZATION:-0}" = "1" ]; then
        echo "ERROR: Production release requires valid Apple Notarization credentials!" >&2
        exit 1
    fi
fi

echo ""
echo "==================================================="
echo "macOS Build Pipeline Completed Successfully!"
echo "  1. App: ${APP_BUNDLE}"
echo "  2. DMG: ${DMG_FILE} ($(du -h "${DMG_FILE}" | cut -f1))"
echo "==================================================="
