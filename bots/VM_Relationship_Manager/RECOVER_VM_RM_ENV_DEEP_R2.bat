@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py ".\RECOVER_VM_RM_ENV_DEEP_R2.py"
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python ".\RECOVER_VM_RM_ENV_DEEP_R2.py"
  exit /b %ERRORLEVEL%
)
echo [X] Python runtime not found.
exit /b 10
