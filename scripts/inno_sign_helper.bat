@echo off
REM Helper script for Inno Setup SignTool to avoid command-line quoting issues
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sign_windows.ps1" -Description "iHRMS Desktop Setup" -Target %1
