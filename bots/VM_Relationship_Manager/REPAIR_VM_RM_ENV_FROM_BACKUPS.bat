@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0REPAIR_VM_RM_ENV_FROM_BACKUPS.ps1"
exit /b %ERRORLEVEL%
