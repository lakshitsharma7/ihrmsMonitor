@echo off
REM Build standalone Windows application and setup installer with Authenticode signing.
REM Run this on Windows.

setlocal enabledelayedexpansion

echo ===================================================
echo [0/5] Preparing Environment and Verifying Dependencies...
echo ===================================================
set "PYTHON_EXE=python"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"

echo Using Python executable: "!PYTHON_EXE!"
taskkill /F /IM "iHRMS-Desktop.exe" 2>nul
taskkill /F /IM "Workpulse.exe" 2>nul
taskkill /F /IM "iHRMS Monitor.exe" 2>nul
"!PYTHON_EXE!" -m pip install -r requirements.txt -r requirements-windows.txt
if errorlevel 1 goto :error

echo.
echo ===================================================
echo [1/5] Building Application Executable with PyInstaller...
echo ===================================================
"!PYTHON_EXE!" scripts\generate_version_info.py
if errorlevel 1 goto :error

set "SPEC_FILE=iHRMS-Desktop.spec"
if not exist "!SPEC_FILE!" (
    echo Spec file not found. Generating iHRMS-Desktop spec...
    pyi-makespec --name "iHRMS-Desktop" --windowed --icon="assets/ihrms-logo-icon.ico" --version-file="file_version_info.txt" --add-data "assets;assets" --paths=. --hidden-import=config --hidden-import=config.settings app.py
    set "SPEC_FILE=iHRMS-Desktop.spec"
)

"!PYTHON_EXE!" -m PyInstaller --noconfirm --clean "!SPEC_FILE!"
if errorlevel 1 goto :error

echo PyInstaller build succeeded at dist\iHRMS-Desktop\iHRMS-Desktop.exe

echo.
echo ===================================================
echo [2/5] Signing Application Executable with Authenticode...
echo ===================================================
if exist "scripts\sign_windows.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\sign_windows.ps1" -Target "dist\iHRMS-Desktop\iHRMS-Desktop.exe" -Description "iHRMS Desktop"
    if errorlevel 1 (
        echo WARNING: Application executable signing encountered an issue.
        if "%REQUIRE_SIGNING%"=="1" goto :error
    )
) else (
    echo WARNING: scripts\sign_windows.ps1 not found.
)

echo.
echo ===================================================
echo [3/5] Compiling Windows Installer with Inno Setup...
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

set "APP_VER=1.0"
if exist "VERSION" set /p APP_VER=<VERSION
echo Using Inno Setup Compiler: "%ISCC%" for Version %APP_VER%
set "ISS_FILE=iHRMS-Desktop.iss"

if not exist "dist\Windows" mkdir "dist\Windows"

"%ISCC%" /DMyAppVersion="%APP_VER%" "!ISS_FILE!"
if errorlevel 1 goto :error

echo Inno Setup compilation succeeded.

echo.
echo ===================================================
echo [4/5] Signing Windows Installer with Authenticode...
echo ===================================================
set "SETUP_EXE=dist\Windows\iHRMS-Desktop-Setup-%APP_VER%.exe"
if exist "!SETUP_EXE!" (
    if exist "scripts\sign_windows.ps1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\sign_windows.ps1" -Target "!SETUP_EXE!" -Description "iHRMS Desktop Setup"
        if errorlevel 1 (
            echo WARNING: Installer signing encountered an issue.
            if "%REQUIRE_SIGNING%"=="1" goto :error
        )
    )
) else (
    echo ERROR: Expected installer not found at !SETUP_EXE!
    goto :error
)

echo.
echo ===================================================
echo [5/5] Verifying Signatures for Executable and Installer...
echo ===================================================
set "VERIFY_ARGS="
if "%REQUIRE_SIGNING%"=="1" set "VERIFY_ARGS=-RequireValid"
if "%REQUIRE_VALID%"=="1" set "VERIFY_ARGS=-RequireValid"
if "%PRODUCTION_BUILD%"=="1" set "VERIFY_ARGS=-RequireValid"

if exist "scripts\verify_windows_signature.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\verify_windows_signature.ps1" -Target "dist\iHRMS-Desktop\iHRMS-Desktop.exe" "!SETUP_EXE!" %VERIFY_ARGS%
    if errorlevel 1 (
        echo ERROR: Signature verification failed for one or more binaries.
        goto :error
    )
) else (
    echo WARNING: scripts\verify_windows_signature.ps1 not found.
)

echo.
echo ===================================================
echo Production Windows Build Complete and Verified:
echo   Application: dist\iHRMS-Desktop\iHRMS-Desktop.exe
echo   Installer:   dist\Windows\iHRMS-Desktop-Setup-%APP_VER%.exe
echo ===================================================
goto :eof

:done_pyinstaller
echo.
echo PyInstaller build completed at dist\iHRMS-Desktop\
goto :eof

:error
echo.
echo Build failed. See output above.
exit /b 1
