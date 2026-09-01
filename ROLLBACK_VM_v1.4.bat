@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ROLLBACK_VM_v1.4.ps1"
pause
