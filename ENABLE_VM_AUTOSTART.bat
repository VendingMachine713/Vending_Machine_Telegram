@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ENABLE_VM_AUTOSTART.ps1"
pause
