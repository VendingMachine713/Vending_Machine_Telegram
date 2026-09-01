@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_VM_RELATIONSHIPS.ps1"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [X] VM Relationship Manager stopped with exit code %RC%.
)

exit /b %RC%
