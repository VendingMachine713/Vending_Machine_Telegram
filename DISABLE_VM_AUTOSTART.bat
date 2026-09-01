@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DISABLE_VM_AUTOSTART.ps1"
pause
