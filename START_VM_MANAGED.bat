@echo off
setlocal
cd /d "%~dp0"
py vm.py start-managed --apply
exit /b %ERRORLEVEL%
