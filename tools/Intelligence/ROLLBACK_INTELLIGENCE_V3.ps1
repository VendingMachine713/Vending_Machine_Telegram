param(
  [string]$BackupPath
)
$ErrorActionPreference='Stop'
$Root=Resolve-Path (Join-Path $PSScriptRoot '..\..')
if(-not $BackupPath){
  $BackupPath=Get-ChildItem (Join-Path $Root 'backups') -Directory -Filter 'pre_vm_intelligence_v3_*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {$_.FullName}
}
if(-not $BackupPath -or -not (Test-Path $BackupPath)){throw 'No VM Intelligence v3 backup folder was found.'}
$BackupPath=(Resolve-Path $BackupPath).Path
Write-Host "VM Intelligence v3 rollback" -ForegroundColor Yellow
Write-Host "Root:   $Root"
Write-Host "Backup: $BackupPath"

# Stop the Intelligence agent before replacing its files/state.
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
 'docs\VM_INTELLIGENCE.md','docs\VM_INTELLIGENCE_PRODUCTION.md','docs\VM_INTELLIGENCE_v3_RELEASE_NOTES.md',
 'config\vm_intelligence.json',
 'config\vm_intelligence_costs.example.json','state\vm_intelligence_release.json'
)){Restore-Rel $rel}

# Restore the consistent database backup if present.
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

# Restore any Admin source file backed up by the installer.
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

Set-Location $Root
$env:PYTHONPATH="$Root;$env:PYTHONPATH"
try{
  py -c "import sys; from pathlib import Path; sys.path.insert(0,r'$Root'); from shared.vm_core.services import restart_service; restart_service('Admin_Command_Centre',Path(r'$Root'),dry_run=False,background=True)"
}catch{}
$Auto=Join-Path $Root 'tools\Intelligence\INSTALL_INTELLIGENCE_AUTOSTART.ps1'
if(Test-Path $Auto){& $Auto}
Write-Host '[OK] VM Intelligence rollback completed.' -ForegroundColor Green
