@echo off
REM Build a standalone Windows executable.
REM Run this FROM Windows - PyInstaller cannot cross-compile a .exe on macOS/Linux.

setlocal

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-windows.txt
if errorlevel 1 goto :error

echo Building ActivityTracker.exe...
pyinstaller --noconfirm --clean --windowed --onefile --name ActivityTracker app.py
if errorlevel 1 goto :error

echo.
echo Build succeeded: dist\ActivityTracker.exe
goto :eof

:error
echo.
echo Build failed. See output above.
exit /b 1
