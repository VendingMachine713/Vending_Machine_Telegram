$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LastFile = Join-Path $Root 'updates\last_update.json'
$HistoryFile = Join-Path $Root 'updates\history.jsonl'
if (-not (Test-Path $LastFile)) { Write-Host 'No last-update metadata found.' -ForegroundColor Yellow; exit 1 }
$last = Get-Content $LastFile -Raw | ConvertFrom-Json
$backup = [string]$last.backup
$metaFile = Join-Path $backup 'rollback.json'
if (-not (Test-Path $metaFile)) { throw "Rollback metadata missing: $metaFile" }
$meta = Get-Content $metaFile -Raw | ConvertFrom-Json
$lock = Join-Path ([string]$meta.target) 'runtime\telegram_runtime.lock'
if (Test-Path $lock) { throw 'Stop the bot before rollback.' }
Write-Host "Rollback $($meta.bot) from $($meta.new_version) to $($meta.previous_version)?" -ForegroundColor Yellow
$answer = Read-Host 'Type ROLLBACK to continue'
if ($answer -ne 'ROLLBACK') { Write-Host 'Cancelled.'; exit 0 }
foreach ($f in @($meta.files)) {
    $dst = Join-Path ([string]$meta.target) ([string]$f.path)
    $bak = Join-Path $backup ([string]$f.path)
    if ($f.existed -and (Test-Path $bak)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Copy-Item $bak $dst -Force
    } elseif (-not $f.existed -and (Test-Path $dst)) {
        Remove-Item $dst -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "[OK] Source rollback complete -> $($meta.previous_version)" -ForegroundColor Green
$dbBackup = Join-Path $backup 'database\smart_autoposter.sqlite3'
if ($meta.database_backup -and (Test-Path $dbBackup)) {
    $dbRel = if ($meta.database_path) { [string]$meta.database_path } else { 'data/smart_autoposter.sqlite3' }
    $dbLive = Join-Path ([string]$meta.target) $dbRel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dbLive) | Out-Null
    Remove-Item ($dbLive + '-wal') -Force -ErrorAction SilentlyContinue
    Remove-Item ($dbLive + '-shm') -Force -ErrorAction SilentlyContinue
    $restoreCode = 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()'
    & py -c $restoreCode $dbBackup $dbLive
    if ($LASTEXITCODE -ne 0) { throw 'Database rollback failed' }
    Write-Host '[OK] Database rollback complete.' -ForegroundColor Green
}
try { ([pscustomobject]@{status='rolled_back';bot=$meta.bot;from_version=$meta.new_version;to_version=$meta.previous_version;at=(Get-Date).ToString('o') } | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding UTF8 } catch {}
Write-Host 'Run the bot health/validation checks before resuming production.' -ForegroundColor DarkGray
