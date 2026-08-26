@echo off
REM Get the directory of this batch file
cd /d "%~dp0"

REM Check if virtual environment directory exists
if not exist "venv" (
    echo Virtual environment 'venv' not found. Creating it...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment. Please ensure Python is installed and in your PATH.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully. Installing dependencies...
    call .\venv\Scripts\activate
    pip install -r requirements.txt -r requirements-windows.txt
) else (
    call .\venv\Scripts\activate
)

echo Starting iHRMS Monitor...
python app.py
if %errorlevel% neq 0 (
    echo Application exited with an error.
    pause
)
