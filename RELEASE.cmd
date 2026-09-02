@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\vm_core\release\VM_RELEASE.ps1"
pause
