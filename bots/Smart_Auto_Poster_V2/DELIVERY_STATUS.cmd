@echo off
setlocal
cd /d "%~dp0"
python SHOW_DELIVERY_STATUS.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Delivery status command failed with exit code %RC%.
)
exit /b %RC%
