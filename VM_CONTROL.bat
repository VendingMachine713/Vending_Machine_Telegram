@echo off
setlocal
cd /d "%~dp0"
:menu
cls
echo ============================================================
echo  VENDING MACHINE - PLATFORM CONTROL
echo ============================================================
echo.
echo  1. Dashboard
echo  2. Status
echo  3. Health
echo  4. VM Doctor
echo  5. Full pre-flight check
echo  6. Sync registries
echo  7. Create backup
echo  8. Create support bundle
echo  9. Run all platform + bot tests
echo 10. Environment report
echo 11. Show recent platform logs
echo 12. Simulate spam scenario
echo 13. Simulate outage scenario
echo 14. Simulate campaign scenario
echo 15. Start a service (preview)
echo 16. Stop a service (preview)
echo 17. Start ALL services (preview)
echo 18. Self-healing supervisor pass (preview)
echo 19. FULL PLATFORM VALIDATION + SUPPORT BUNDLE
echo 20. Developer tools status/install preview
echo 21. Git status
echo 22. Start Admin Command Centre (preview)
echo 23. Universal Search refresh
echo 24. VM Guard pass
echo 25. Show open alerts
echo 26. Start managed services in background
echo 27. Live runtime snapshot
echo 28. Autostart status
echo 29. Legacy Search/Guard recovery preview
echo 30. Relationship duplicate cleanup preview
echo 31. Create readable support TXT
echo 32. Runtime verification
echo 33. Git tracked-file security audit
echo 34. Storage audit
echo  0. Exit
echo.
set /p choice=Choose:
if "%choice%"=="1" py vm.py dashboard
if "%choice%"=="2" py vm.py status
if "%choice%"=="3" py vm.py health
if "%choice%"=="4" py vm.py doctor
if "%choice%"=="5" py vm.py check
if "%choice%"=="6" py vm.py registry sync
if "%choice%"=="7" py vm.py backup create
if "%choice%"=="8" py vm.py support
if "%choice%"=="9" py vm.py test-all
if "%choice%"=="10" py vm.py env
if "%choice%"=="11" py vm.py logs platform --lines 50
if "%choice%"=="12" py vm.py simulate spam
if "%choice%"=="13" py vm.py simulate outage
if "%choice%"=="14" py vm.py simulate campaign
if "%choice%"=="15" (
  set /p svc=Service name:
  py vm.py start "%svc%"
)
if "%choice%"=="16" (
  set /p svc=Service name:
  py vm.py stop "%svc%"
)
if "%choice%"=="17" py vm.py start all
if "%choice%"=="18" py vm.py supervise
if "%choice%"=="19" py vm.py validate-all
if "%choice%"=="20" py vm.py dev-tools
if "%choice%"=="21" py vm.py git-status
if "%choice%"=="22" py vm.py start Admin_Command_Centre
if "%choice%"=="23" py vm.py search-refresh
if "%choice%"=="24" py vm.py guard
if "%choice%"=="25" py vm.py alerts
if "%choice%"=="26" py vm.py start-managed --apply
if "%choice%"=="27" py vm.py runtime
if "%choice%"=="28" py vm.py autostart-status
if "%choice%"=="29" py vm.py legacy-recovery
if "%choice%"=="30" py vm.py relationship-cleanup
if "%choice%"=="31" py vm.py support-text
if "%choice%"=="32" py vm.py runtime-check
if "%choice%"=="33" py vm.py git-audit
if "%choice%"=="34" py vm.py storage
if "%choice%"=="0" exit /b 0
echo.
pause
goto menu
