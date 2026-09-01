@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0APPLY_RELATIONSHIP_CLEANUP.ps1"
pause
