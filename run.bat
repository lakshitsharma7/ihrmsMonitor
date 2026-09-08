@echo off
REM Get the directory of this batch file
cd /d "%~dp0"

REM Check if virtual environment directory exists and has activation script
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment 'venv' is missing or incomplete. Setting it up...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment. Please ensure Python is installed and in your PATH.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully. Installing dependencies...
    call ".\venv\Scripts\activate.bat"
    pip install -r requirements.txt -r requirements-windows.txt
) else (
    call ".\venv\Scripts\activate.bat"
)

echo Starting iHRMS Monitor...
".\venv\Scripts\python.exe" app.py
if %errorlevel% neq 0 (
    echo Application exited with an error.
    pause
)
