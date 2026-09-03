@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  VM WINDOWS -^> GITHUB SAFE RECONCILIATION
echo ============================================================
echo.
echo This creates a private sync branch. It does NOT push to main.
echo Runtime/generated paths and obvious secrets are safety-gated.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SYNC_WINDOWS_TO_GITHUB.ps1" -Apply
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [FAILED] Safe reconciliation stopped before completion.
  echo No direct push to main was performed.
) else (
  echo [DONE] Safe source branch was pushed to GitHub.
)
echo.
pause
exit /b %RC%
