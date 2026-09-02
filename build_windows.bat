@echo off
REM Build standalone Windows application and setup installer.
REM Run this on Windows.

setlocal enabledelayedexpansion

echo ===================================================
echo [1/3] Installing / Verifying Dependencies...
echo ===================================================
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-windows.txt
if errorlevel 1 goto :error

echo.
echo ===================================================
echo [2/3] Generating Version Info & Building with PyInstaller...
echo ===================================================
python scripts\generate_version_info.py
if errorlevel 1 goto :error

pyinstaller --noconfirm --clean "IHRMS Monitor.spec"
if errorlevel 1 goto :error

echo.
echo PyInstaller build succeeded in dist\iHRMS Monitor\

echo.
echo ===================================================
echo [3/3] Compiling Windows Installer with Inno Setup...
echo ===================================================
set "ISCC="

if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
) else (
    for %%i in (ISCC.exe) do set "ISCC=%%~$PATH:i"
)

if not defined ISCC (
    echo WARNING: Inno Setup Compiler ^(ISCC.exe^) not found.
    echo Please install Inno Setup 6 or add ISCC.exe to PATH to build the installer.
    goto :done_pyinstaller
)

for /f "delims=" %%v in ('python -c "from config.settings import APP_VERSION; print(APP_VERSION)"') do set "APP_VER=%%v"
echo Using Inno Setup Compiler: "%ISCC%" for Version %APP_VER%
"%ISCC%" /DMyAppVersion="%APP_VER%" "IHRMS Monitor.iss"
if errorlevel 1 goto :error

echo.
echo ===================================================
echo Installer Build Complete: dist\installer\iHRMSMonitorSetup.exe
echo ===================================================
goto :eof

:done_pyinstaller
echo.
echo PyInstaller build completed at dist\iHRMS Monitor\
goto :eof

:error
echo.
echo Build failed. See output above.
exit /b 1
