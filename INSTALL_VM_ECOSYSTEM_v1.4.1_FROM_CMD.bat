@echo off
setlocal EnableExtensions
title VM Ecosystem v1.4.1 Installer

set "VMROOT=%USERPROFILE%\OneDrive\Desktop\Vending_Machine_Telegram"
if not exist "%VMROOT%\bots" set "VMROOT=%USERPROFILE%\Desktop\Vending_Machine_Telegram"

echo.
echo ================================================================
echo  VM ECOSYSTEM v1.4.1 - ONE CLICK LIVE CLEANUP
echo ================================================================
echo.

if not exist "%VMROOT%\bots" (
  echo [ERROR] Could not find Vending_Machine_Telegram\bots.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='Stop';" ^
 "$locations=@((Join-Path $env:USERPROFILE 'Downloads'),(Join-Path $env:USERPROFILE 'Desktop'),(Join-Path $env:USERPROFILE 'OneDrive\Desktop'));" ^
 "$zip=Get-ChildItem -Path $locations -Filter 'VM_Ecosystem_v1.4.1_DIRECT_DROP*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1;" ^
 "if(-not $zip){Write-Host '[ERROR] VM_Ecosystem_v1.4.1_DIRECT_DROP.zip not found.' -ForegroundColor Red; exit 3};" ^
 "$root='%VMROOT%'; Set-Location -LiteralPath $root;" ^
 "foreach($svc in @('Admin_Command_Centre','Universal_Search','VM_Guard')){try{py .\vm.py stop $svc --apply | Out-Null}catch{}};" ^
 "$stamp=Get-Date -Format 'yyyyMMdd_HHmmss';" ^
 "$pre=Join-Path $root ('backups\pre_v1_4_1_ecosystem_'+$stamp);" ^
 "New-Item -ItemType Directory -Force -Path $pre | Out-Null;" ^
 "$items=@('vm.py','VM_PROJECT.json','pyproject.toml','shared','tools','tests','docs','README_VM_PLATFORM.md','CHANGELOG_VM_PLATFORM.md','APPLY_RELATIONSHIP_CLEANUP.ps1','APPLY_RELATIONSHIP_CLEANUP.bat','config\vm_platform.json','VM_CONTROL.bat','.gitignore','START_VM_MANAGED.bat','ENABLE_VM_AUTOSTART.ps1','ENABLE_VM_AUTOSTART.bat','DISABLE_VM_AUTOSTART.ps1','DISABLE_VM_AUTOSTART.bat','bots\Admin_Command_Centre','bots\Universal_Search','bots\VM_Guard','bots\VM_Relationship_Manager');" ^
 "foreach($i in $items){$src=Join-Path $root $i;if(Test-Path $src){$dst=Join-Path $pre $i;$parent=Split-Path $dst -Parent;New-Item -ItemType Directory -Force -Path $parent|Out-Null;Copy-Item $src $dst -Recurse -Force}};" ^
 "$sap=Join-Path $root 'bots\Smart_Auto_Poster_V2';$sapPre=Join-Path $pre 'bots\Smart_Auto_Poster_V2';" ^
 "foreach($rel in @('CONTROL_PANEL.ps1','GO_LIVE.ps1','master_updater\APPLY_UPDATE.ps1')){$src=Join-Path $sap $rel;if(Test-Path $src){$dst=Join-Path $sapPre $rel;New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null;Copy-Item $src $dst -Force}};" ^
 "Write-Host ('[OK] Pre-v1.4.1 safety snapshot: '+$pre) -ForegroundColor Green;" ^
 "Expand-Archive -LiteralPath $zip.FullName -DestinationPath $root -Force;" ^
 "$env:VM_PREINSTALL_SNAPSHOT=$pre;" ^
 "Set-Location -LiteralPath $root;" ^
 "& '.\INSTALL_VM_ECOSYSTEM_v1.4.1.ps1';" ^
 "exit $LASTEXITCODE"

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
 echo [OK] VM Ecosystem v1.4.1 rollout completed.
 echo [NEXT] Upload %%USERPROFILE%%\Downloads\VM_SUPPORT_READABLE.txt to ChatGPT.
) else if "%RC%"=="3" (
 echo [ACTION] Put VM_Ecosystem_v1.4.1_DIRECT_DROP.zip in Downloads and run this again.
) else (
 echo [WARNING] Installer returned exit code %RC%.
)
echo.
pause
exit /b %RC%
