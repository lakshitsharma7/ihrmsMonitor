#!/usr/bin/env bash
# Build a standalone macOS .app bundle.
# Run this FROM macOS - PyInstaller cannot cross-compile a .app on Windows/Linux.

set -euo pipefail

echo "Installing dependencies..."
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt -r requirements-macos.txt

echo "Building IHRMSMonitor.app..."
pyinstaller --noconfirm --clean --windowed --name IHRMSMonitor app.py

echo
echo "Build succeeded: dist/IHRMSMonitor.app"
echo "Note: on first run, macOS will ask you to grant Accessibility / Screen"
echo "Recording permission for window-title detection to work (System Settings ->"
echo "Privacy & Security)."
