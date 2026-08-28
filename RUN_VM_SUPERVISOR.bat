@echo off
cd /d "%~dp0"
echo VM Supervisor - Ctrl+C to stop
py vm.py supervise-loop --apply --interval 60
pause
