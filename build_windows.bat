@echo off
REM Build standalone Windows application and setup installer.
REM Run this on Windows.

setlocal enabledelayedexpansion

echo ===================================================
echo [1/3] Preparing Environment and Verifying Dependencies...
echo ===================================================
set "PYTHON_EXE=python"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"

echo Using Python executable: "!PYTHON_EXE!"
taskkill /F /IM "Workpulse.exe" 2>nul
taskkill /F /IM "iHRMS Monitor.exe" 2>nul
"!PYTHON_EXE!" -m pip install -r requirements.txt -r requirements-windows.txt
if errorlevel 1 goto :error

echo.
echo ===================================================
echo [2/3] Generating Version Info and Building with PyInstaller...
echo ===================================================
"!PYTHON_EXE!" scripts\generate_version_info.py
if errorlevel 1 goto :error

set "SPEC_FILE=Workpulse.spec"
if not exist "!SPEC_FILE!" (
    echo Spec file not found. Generating Workpulse spec...
    pyi-makespec --name "Workpulse" --windowed --icon="assets/ihrms-logo-icon.ico" --version-file="file_version_info.txt" --add-data "assets;assets" --paths=. --hidden-import=config --hidden-import=config.settings app.py
    set "SPEC_FILE=Workpulse.spec"
)

"!PYTHON_EXE!" -m PyInstaller --noconfirm --clean "!SPEC_FILE!"
if errorlevel 1 goto :error

echo.
echo PyInstaller build succeeded in dist\Workpulse\

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

set "APP_VER=2.0.2"
if exist "VERSION" set /p APP_VER=<VERSION
echo Using Inno Setup Compiler: "%ISCC%" for Version %APP_VER%
set "ISS_FILE=Workpulse.iss"
"%ISCC%" /DMyAppVersion="%APP_VER%" "!ISS_FILE!"
if errorlevel 1 goto :error

if not exist "dist\installer" mkdir "dist\installer"
if exist "installer\WorkpulseSetup.exe" copy /y "installer\WorkpulseSetup.exe" "dist\installer\WorkpulseSetup.exe"
if exist "installer\WorkpulseSetup.exe" copy /y "installer\WorkpulseSetup.exe" "dist\installer\iHRMSMonitorSetup.exe"
if exist "installer\Workpulse-Installer.exe" copy /y "installer\Workpulse-Installer.exe" "dist\installer\WorkpulseSetup.exe"
if exist "installer\Workpulse-Installer.exe" copy /y "installer\Workpulse-Installer.exe" "dist\installer\iHRMSMonitorSetup.exe"

echo.
echo ===================================================
echo Installer Build Complete:
echo   1. installer\Workpulse-Installer.exe
echo   2. dist\installer\WorkpulseSetup.exe
echo ===================================================
goto :eof


:done_pyinstaller
echo.
echo PyInstaller build completed at dist\Workpulse\
goto :eof

:error
echo.
echo Build failed. See output above.
exit /b 1
