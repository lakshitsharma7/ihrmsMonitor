#!/usr/bin/env bash
# Build a standalone macOS .app bundle.
# Run this FROM macOS - PyInstaller cannot cross-compile a .app on Windows/Linux.

set -euo pipefail

echo "Installing dependencies..."
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt -r requirements-macos.txt

echo "Building IHRMS Monitor.app..."
pyinstaller --noconfirm --clean --windowed --name "IHRMS Monitor" --paths=. --hidden-import=config --hidden-import=config.settings --add-data "assets:assets" app.py

echo
echo "Build succeeded: dist/IHRMS Monitor.app"
echo "Note: on first run, macOS will ask you to grant Accessibility / Screen"
echo "Recording permission for window-title detection to work (System Settings ->"
echo "Privacy & Security)."
