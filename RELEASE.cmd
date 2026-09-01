@echo off
cd /d "C:\Users\cherr\OneDrive\Desktop\Vending_Machine_Telegram"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\vm_core\release\VM_RELEASE.ps1"
pause
