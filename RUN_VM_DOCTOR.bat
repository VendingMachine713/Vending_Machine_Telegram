@echo off
setlocal
cd /d "%~dp0"
py vm.py doctor
echo.
pause
