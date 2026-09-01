param(
  [string]$BackupPath
)
$ErrorActionPreference='Stop'
$Root=Resolve-Path (Join-Path $PSScriptRoot '..\..')
if(-not $BackupPath){
  $BackupPath=Get-ChildItem (Join-Path $Root 'backups') -Directory -Filter 'pre_vm_intelligence_v4_*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {$_.FullName}
}
if(-not $BackupPath -or -not (Test-Path $BackupPath)){throw 'No VM Intelligence v4 backup folder was found.'}
$BackupPath=(Resolve-Path $BackupPath).Path
Write-Host 'VM Intelligence v4 rollback' -ForegroundColor Yellow
Write-Host "Root:   $Root"
Write-Host "Backup: $BackupPath"

# Keep a temporary copy of the bridge before tools are restored, because the pre-v4
# tools snapshot may not contain it. The bridge itself contains no credentials.
$BridgeTemp=$null
$BridgeCurrent=Join-Path $Root 'tools\Intelligence\RUNTIME_BRIDGE.py'
if(Test-Path $BridgeCurrent){
  $BridgeTemp=Join-Path $env:TEMP ("VM_RUNTIME_BRIDGE_ROLLBACK_"+[guid]::NewGuid().ToString('N')+'.py')
  Copy-Item $BridgeCurrent $BridgeTemp -Force
}

# Stop Intelligence before replacing its code and SQLite state.
$me=$PID
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $_.ProcessId -ne $me -and $_.Name -match 'python|py' -and
  $_.CommandLine -match 'shared\.vm_intelligence\.cli' -and $_.CommandLine -match '\bagent\b'
} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
Start-Sleep -Seconds 1

function Restore-Rel([string]$rel){
  $src=Join-Path $BackupPath $rel
  $dst=Join-Path $Root $rel
  if(Test-Path $src){
    Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
    Write-Host "[RESTORED] $rel"
  }
}

foreach($rel in @(
 'shared\vm_intelligence','tools\Intelligence','tests\vm_intelligence',
 'docs\VM_INTELLIGENCE.md','docs\VM_INTELLIGENCE_PRODUCTION.md',
 'docs\VM_INTELLIGENCE_v3_RELEASE_NOTES.md','docs\VM_INTELLIGENCE_v4_RELEASE_NOTES.md',
 'config\vm_intelligence.json','config\vm_intelligence_costs.example.json',
 'state\vm_intelligence_release.json'
)){Restore-Rel $rel}

# Restore consistent Intelligence DB snapshot and verify it before continuing.
$DbBackup=Join-Path $BackupPath 'state\vm_intelligence.sqlite3'
if(Test-Path $DbBackup){
  Remove-Item (Join-Path $Root 'state\vm_intelligence.sqlite3') -Force -ErrorAction SilentlyContinue
  Remove-Item (Join-Path $Root 'state\vm_intelligence.sqlite3-wal') -Force -ErrorAction SilentlyContinue
  Remove-Item (Join-Path $Root 'state\vm_intelligence.sqlite3-shm') -Force -ErrorAction SilentlyContinue
  Copy-Item $DbBackup (Join-Path $Root 'state\vm_intelligence.sqlite3') -Force
  $env:VM_INT_ROLLBACK_DB=Join-Path $Root 'state\vm_intelligence.sqlite3'
  py -c "import os,sqlite3; c=sqlite3.connect(os.environ['VM_INT_ROLLBACK_DB']); ok=c.execute('PRAGMA quick_check').fetchone()[0]; c.close(); raise SystemExit(0 if str(ok).lower()=='ok' else 2)"
  if($LASTEXITCODE-ne 0){throw 'Restored Intelligence database failed integrity validation.'}
  Remove-Item Env:VM_INT_ROLLBACK_DB -ErrorAction SilentlyContinue
  Write-Host '[RESTORED] state\vm_intelligence.sqlite3'
}

# Restore backed-up Admin integration source, if this release changed it.
$AdminBackup=Get-ChildItem $BackupPath -Filter admin_core.py -File -Recurse -ErrorAction SilentlyContinue |
  Sort-Object {$_.FullName.Length} | Select-Object -First 1
if($AdminBackup){
  $rel=$AdminBackup.FullName.Substring($BackupPath.Length).TrimStart('\')
  $target=Join-Path $Root $rel
  New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent)|Out-Null
  Copy-Item $AdminBackup.FullName $target -Force
  py -m py_compile "$target"
  if($LASTEXITCODE-ne 0){throw 'Restored Admin Command Centre source failed syntax validation.'}
  Write-Host "[RESTORED] $rel"
}

# VM Core recovery and runtime compatibility shims are intentionally NOT deleted: they
# repair pre-existing platform drift and were validated before v4 feature mutation.
Set-Location $Root
$env:PYTHONPATH="$Root;$env:PYTHONPATH"
try{
  if($BridgeTemp -and (Test-Path (Join-Path $Root 'state\runtime_bridge.json'))){
    py "$BridgeTemp" --root "$Root" --report (Join-Path $Root 'diagnostics\runtime_bridge_rollback_status.json') --mode ensure
    if($LASTEXITCODE-ne 0){Write-Host '[WARN] Runtime bridge could not fully re-establish desired state during rollback.' -ForegroundColor Yellow}
  }
}catch{Write-Host "[WARN] Runtime bridge rollback recovery: $($_.Exception.Message)" -ForegroundColor Yellow}
finally{if($BridgeTemp){Remove-Item $BridgeTemp -Force -ErrorAction SilentlyContinue}}

$Auto=Join-Path $Root 'tools\Intelligence\INSTALL_INTELLIGENCE_AUTOSTART.ps1'
if(Test-Path $Auto){& $Auto}
Write-Host '[OK] VM Intelligence v4 rollback completed.' -ForegroundColor Green
