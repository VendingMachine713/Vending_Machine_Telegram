@echo off
setlocal EnableExtensions
title VM Platform v1.4.3 Maintenance Installer

set "VMROOT=%USERPROFILE%\OneDrive\Desktop\Vending_Machine_Telegram"
if not exist "%VMROOT%\bots" set "VMROOT=%USERPROFILE%\Desktop\Vending_Machine_Telegram"

echo.
echo ================================================================
echo  VM PLATFORM v1.4.3 - VERSION-ADAPTIVE MAINTENANCE
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
 "$zip=Get-ChildItem -Path $locations -Filter 'VM_Ecosystem_v1.4.3_MAINTENANCE*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1;" ^
 "if(-not $zip){Write-Host '[ERROR] VM_Ecosystem_v1.4.3_MAINTENANCE.zip not found.' -ForegroundColor Red; exit 3};" ^
 "$root='%VMROOT%'; Set-Location -LiteralPath $root;" ^
 "$stamp=Get-Date -Format 'yyyyMMdd_HHmmss';" ^
 "$pre=Join-Path $root ('backups\pre_v1_4_3_ecosystem_'+$stamp);" ^
 "New-Item -ItemType Directory -Force -Path $pre | Out-Null;" ^
 "$items=@('shared','tools','tests','VM_CONTROL.bat','CHANGELOG_VM_PLATFORM.md','VM_PROJECT.json','pyproject.toml');" ^
 "foreach($i in $items){$src=Join-Path $root $i;if(Test-Path $src){$dst=Join-Path $pre $i;$parent=Split-Path $dst -Parent;New-Item -ItemType Directory -Force -Path $parent|Out-Null;Copy-Item $src $dst -Recurse -Force}};" ^
 "$sap=Join-Path $root 'bots\Smart_Auto_Poster_V2'; $sapSave=Join-Path $pre 'sap_targets';" ^
 "foreach($rel in @('CONTROL_PANEL.ps1','GO_LIVE.ps1','master_updater\APPLY_UPDATE.ps1','DRIFT_REPAIR_VM_1_4_3.json')){" ^
 "  $src=Join-Path $sap $rel; $dst=Join-Path $sapSave $rel;" ^
 "  if(Test-Path -LiteralPath $src){New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null;Copy-Item -LiteralPath $src -Destination $dst -Force}" ^
 "  else {$marker=Join-Path $sapSave ($rel+'.missing');New-Item -ItemType Directory -Force -Path (Split-Path $marker -Parent)|Out-Null;New-Item -ItemType File -Force -Path $marker|Out-Null}" ^
 "};" ^
 "Write-Host ('[OK] Pre-v1.4.3 rollback snapshot: '+$pre) -ForegroundColor Green;" ^
 "Expand-Archive -LiteralPath $zip.FullName -DestinationPath $root -Force;" ^
 "$env:VM_PRE143_SNAPSHOT=$pre;" ^
 "Set-Location -LiteralPath $root;" ^
 "& '.\INSTALL_VM_1_4_3_MAINTENANCE.ps1';" ^
 "exit $LASTEXITCODE"

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] VM Platform v1.4.3 maintenance completed.
  echo [NEXT] Upload %%USERPROFILE%%\Downloads\VM_SUPPORT_READABLE.txt to ChatGPT.
) else if "%RC%"=="3" (
  echo [ACTION] Put VM_Ecosystem_v1.4.3_MAINTENANCE.zip in Downloads and run this installer again.
) else (
  echo [WARNING] Maintenance installer returned exit code %RC%.
  echo [NEXT] Upload %%USERPROFILE%%\Downloads\VM_MAINTENANCE_RESULT.txt to ChatGPT.
)
echo.
pause
exit /b %RC%
