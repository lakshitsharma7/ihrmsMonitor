@echo off
REM Build a standalone Windows executable.
REM Run this FROM Windows - PyInstaller cannot cross-compile a .exe on macOS/Linux.

setlocal

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-windows.txt
if errorlevel 1 goto :error

echo Building "iHRMS Monitor.exe"...
pyinstaller --noconfirm --clean --windowed --onefile --name "iHRMS Monitor" --paths=. --hidden-import=config --hidden-import=config.settings --add-data "assets;assets" app.py
if errorlevel 1 goto :error

echo.
echo Build succeeded: dist\"iHRMS Monitor.exe"
goto :eof

:error
echo.
echo Build failed. See output above.
exit /b 1
