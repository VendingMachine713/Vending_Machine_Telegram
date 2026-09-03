@echo off
setlocal
cd /d "%~dp0"
py ".\RECOVER_VM_RM_ENV_DEEP.py"
if errorlevel 1 (
  python ".\RECOVER_VM_RM_ENV_DEEP.py"
)
exit /b %ERRORLEVEL%
