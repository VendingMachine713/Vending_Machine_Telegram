@echo off
setlocal
cd /d "%~dp0"
py ".\VERIFY_VM_RM_V6_LIVE_STATE.py"
if errorlevel 1 exit /b %ERRORLEVEL%
exit /b 0
