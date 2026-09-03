$ErrorActionPreference = 'Stop'

function Copy-ItemRetry {
    param([string]$Source,[string]$Destination,[int]$Attempts=4)
    $last = $null
    for ($i=1; $i -le $Attempts; $i++) {
        try {
            Copy-Item -LiteralPath $Source -Destination $Destination -Force -ErrorAction Stop
            return
        } catch {
            $last = $_
            [GC]::Collect(); [GC]::WaitForPendingFinalizers()
            Start-Sleep -Seconds ([Math]::Min(6,$i * 2))
        }
    }
    throw "Copy failed after $Attempts attempt(s): $Source -> $Destination | $($last.Exception.Message)"
}
function Invoke-PythonRetry {
    param([string[]]$Arguments,[int]$Attempts=3)
    for ($i=1; $i -le $Attempts; $i++) {
        try {
            & py @Arguments
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
        Start-Sleep -Seconds ([Math]::Min(6,$i * 2))
    }
    return $false
}

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
$sourceErrors = @()
foreach ($f in @($meta.files)) {
    try {
        $dst = Join-Path ([string]$meta.target) ([string]$f.path)
        $bak = Join-Path $backup ([string]$f.path)
        if ($f.existed -and (Test-Path $bak)) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-ItemRetry -Source $bak -Destination $dst
        } elseif (-not $f.existed -and (Test-Path $dst)) {
            Remove-Item $dst -Force -ErrorAction SilentlyContinue
        }
    } catch {
        $sourceErrors += ("{0}: {1}" -f ([string]$f.path), $_.Exception.Message)
    }
}
if ($sourceErrors.Count -eq 0) {
    Write-Host "[OK] Source rollback complete -> $($meta.previous_version)" -ForegroundColor Green
} else {
    Write-Host "[WARNING] $($sourceErrors.Count) source file(s) could not be restored; database rollback will still be attempted." -ForegroundColor Yellow
}
$dbBackup = Join-Path $backup 'database\smart_autoposter.sqlite3'
if ($meta.database_backup -and (Test-Path $dbBackup)) {
    $dbRel = if ($meta.database_path) { [string]$meta.database_path } else { 'data/smart_autoposter.sqlite3' }
    $dbLive = Join-Path ([string]$meta.target) $dbRel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dbLive) | Out-Null
    Remove-Item ($dbLive + '-wal') -Force -ErrorAction SilentlyContinue
    Remove-Item ($dbLive + '-shm') -Force -ErrorAction SilentlyContinue
    $restoreCode = 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()'
    if (-not (Invoke-PythonRetry -Arguments @('-c',$restoreCode,$dbBackup,$dbLive))) { throw 'Database rollback failed' }
    Write-Host '[OK] Database rollback complete.' -ForegroundColor Green
}
try { ([pscustomobject]@{status='rolled_back';bot=$meta.bot;from_version=$meta.new_version;to_version=$meta.previous_version;at=(Get-Date).ToString('o') } | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding UTF8 } catch {}
$sourceErrors | ForEach-Object { Write-Host "[SOURCE ROLLBACK ERROR] $_" -ForegroundColor Red }
Write-Host 'Run the bot health/validation checks before resuming production.' -ForegroundColor DarkGray
if ($sourceErrors.Count -gt 0) { exit 2 }
