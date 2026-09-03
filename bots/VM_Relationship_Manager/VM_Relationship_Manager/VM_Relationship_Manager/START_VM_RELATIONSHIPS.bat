@echo off
cd /d "%~dp0"
title VM Relationship Manager

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_VM_RELATIONSHIPS.ps1"

echo.
echo VM Relationship Manager has stopped.
pause
