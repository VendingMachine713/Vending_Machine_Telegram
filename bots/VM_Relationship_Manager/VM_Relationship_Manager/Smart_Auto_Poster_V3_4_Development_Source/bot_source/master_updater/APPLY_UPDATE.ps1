param([string]$Package)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Updates = Join-Path $Root 'updates'
$Inbox = Join-Path $Updates 'inbox'
$Applied = Join-Path $Updates 'applied'
$Failed = Join-Path $Updates 'failed'
$Backups = Join-Path $Updates 'backups'
$LocalBackups = Join-Path $env:LOCALAPPDATA 'Vending_Machine_Telegram\update_backups'
$HistoryFile = Join-Path $Updates 'history.jsonl'
@($Inbox,$Applied,$Failed,$Backups,$LocalBackups) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }


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
    $lastExit = 999
    for ($i=1; $i -le $Attempts; $i++) {
        try {
            & py @Arguments
            $lastExit = $LASTEXITCODE
            if ($lastExit -eq 0) { return $true }
        } catch { $lastExit = 998 }
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
        Start-Sleep -Seconds ([Math]::Min(6,$i * 2))
    }
    return $false
}

function Base-Version([string]$Value) {
    if (-not $Value) { return [version]'0.0.0' }
    $clean = ($Value -split '-')[0]
    try { return [version]$clean } catch { return [version]'0.0.0' }
}
function Fail-Update([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    throw $Message
}
function Has-ParentTraversal([string]$Value) {
    if (-not $Value) { return $false }
    if ([IO.Path]::IsPathRooted($Value)) { return $true }
    foreach ($seg in ($Value -split '[\\/]')) {
        if ($seg -eq '..') { return $true }
    }
    return $false
}

if (-not $Package) {
    $item = Get-ChildItem $Inbox -Filter '*.zip' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $item) { Write-Host "No update ZIP found in $Inbox" -ForegroundColor Yellow; exit 1 }
    $Package = $item.FullName
}
if (-not (Test-Path $Package)) { Fail-Update "Update package not found: $Package" }

$Temp = Join-Path $env:TEMP ("VM_UPDATE_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Temp | Out-Null
$backupDir = $null
$dbBackupFile = $null
$dbLiveFile = $null
try {
    Expand-Archive -Path $Package -DestinationPath $Temp -Force
    $manifestFile = Get-ChildItem $Temp -Filter 'update_manifest.json' -Recurse -File | Select-Object -First 1
    if (-not $manifestFile) { Fail-Update 'update_manifest.json is missing' }
    $manifest = Get-Content $manifestFile.FullName -Raw | ConvertFrom-Json
    if (-not $manifest.bot -or -not $manifest.version -or -not $manifest.target) { Fail-Update 'Manifest missing bot/version/target' }
    if ($manifest.format_version -and [int]$manifest.format_version -gt 3) { Fail-Update "Unsupported update manifest format: $($manifest.format_version)" }
    $targetRel = ([string]$manifest.target).Replace('\','/')
    if ((Has-ParentTraversal $targetRel) -or -not $targetRel.StartsWith('bots/')) { Fail-Update "Unsafe manifest target: $targetRel" }
    $payload = Join-Path $manifestFile.Directory.FullName 'payload'
    if (-not (Test-Path $payload)) { Fail-Update 'Manifest payload folder is missing' }

    # V3.0 verifies payload membership and optional SHA-256 hashes before touching the installed bot.
    $payloadFiles = Get-ChildItem $payload -Recurse -File
    if ($manifest.files) {
        $actual = @($payloadFiles | ForEach-Object { $_.FullName.Substring($payload.Length).TrimStart('\','/').Replace('\','/') } | Sort-Object)
        $declared = @($manifest.files | ForEach-Object { ([string]$_).Replace('\','/') } | Sort-Object)
        if (Compare-Object $actual $declared) { Fail-Update 'Payload files do not exactly match manifest.files' }
    }
    if ($manifest.sha256) {
        foreach ($prop in $manifest.sha256.PSObject.Properties) {
            $rel = ([string]$prop.Name).Replace('/','\')
            if (Has-ParentTraversal $rel) { Fail-Update "Unsafe hash path: $rel" }
            $file = Join-Path $payload $rel
            if (-not (Test-Path $file)) { Fail-Update "Hashed payload file missing: $rel" }
            $actualHash = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLowerInvariant()
            $expectedHash = ([string]$prop.Value).ToLowerInvariant()
            if ($actualHash -ne $expectedHash) { Fail-Update "SHA-256 mismatch: $rel" }
        }
    }

    $Target = Join-Path $Root $targetRel
    if (-not (Test-Path $Target)) { Fail-Update "Target bot folder does not exist: $Target" }
    $lock = Join-Path $Target 'runtime\telegram_runtime.lock'
    if (Test-Path $lock) { Fail-Update 'The bot appears to be running. Stop it before applying an update.' }

    $currentVersionFile = Join-Path $Target 'VERSION.txt'
    $current = if (Test-Path $currentVersionFile) { (Get-Content $currentVersionFile -Raw).Trim() } else { '0.0.0' }
    if ($manifest.requires_min -and (Base-Version $current) -lt (Base-Version ([string]$manifest.requires_min))) {
        Fail-Update "Current version $current is older than required $($manifest.requires_min)"
    }
    if ($manifest.requires_max -and (Base-Version $current) -gt (Base-Version ([string]$manifest.requires_max))) {
        Fail-Update "Current version $current is newer than supported $($manifest.requires_max)"
    }
    if ((Base-Version ([string]$manifest.version)) -le (Base-Version $current)) {
        Fail-Update "Update version $($manifest.version) is not newer than installed version $current. Use rollback for a downgrade."
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupDir = Join-Path $LocalBackups ("$($manifest.bot)_$($manifest.version)_$stamp")
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $fileMeta = @()
    foreach ($src in $payloadFiles) {
        $rel = $src.FullName.Substring($payload.Length).TrimStart('\','/')
        $dst = Join-Path $Target $rel
        $existed = Test-Path $dst
        $fileMeta += [pscustomobject]@{ path=$rel; existed=$existed }
        if ($existed) {
            $bak = Join-Path $backupDir $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bak) | Out-Null
            Copy-ItemRetry -Source $dst -Destination $bak
        }
    }
    $rollbackMeta = [pscustomobject]@{ target=$Target; bot=$manifest.bot; previous_version=$current; new_version=$manifest.version; files=$fileMeta; database_backup=[bool]$manifest.database_backup; database_path=$(if ($manifest.database_path) { [string]$manifest.database_path } else { 'data/smart_autoposter.sqlite3' }) }
    $rollbackMeta | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $backupDir 'rollback.json') -Encoding UTF8
    try {
        $pointer = [pscustomobject]@{ backup=$backupDir; bot=$manifest.bot; version=$manifest.version; previous_version=$current; created_at=(Get-Date).ToString('o') }
        $pointer | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $Backups ("$($manifest.bot)_$($manifest.version)_$stamp.pointer.json")) -Encoding UTF8
    } catch {}

    # Consistent SQLite online backup before any source/migration changes. V3 keeps this
    # backup beside the source rollback metadata so a failed post-update migration can
    # restore both code and database to the same pre-update state.
    if ($manifest.database_backup) {
        $dbRel = if ($manifest.database_path) { ([string]$manifest.database_path).Replace('/', '\\') } else { 'data\smart_autoposter.sqlite3' }
        if (Has-ParentTraversal $dbRel) { Fail-Update "Unsafe database_path: $dbRel" }
        $dbLiveFile = Join-Path $Target $dbRel
        if (Test-Path $dbLiveFile) {
            $dbDir = Join-Path $backupDir 'database'
            New-Item -ItemType Directory -Force -Path $dbDir | Out-Null
            $dbBackupFile = Join-Path $dbDir 'smart_autoposter.sqlite3'
            $backupCode = 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()'
            if (-not (Invoke-PythonRetry -Arguments @('-c',$backupCode,$dbLiveFile,$dbBackupFile))) { Fail-Update 'SQLite online backup failed before update' }
            if (-not (Test-Path $dbBackupFile)) { Fail-Update 'SQLite online backup file missing after update backup' }
        }
    }

    foreach ($src in $payloadFiles) {
        $rel = $src.FullName.Substring($payload.Length).TrimStart('\','/')
        $dst = Join-Path $Target $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Copy-ItemRetry -Source $src.FullName -Destination $dst
    }

    Push-Location $Target
    try {
        foreach ($cmd in @($manifest.post_update)) {
            if (-not $cmd) { continue }
            Write-Host "> $cmd" -ForegroundColor DarkGray
            & cmd.exe /d /s /c $cmd
            if ($LASTEXITCODE -ne 0) { Fail-Update "Post-update command failed ($LASTEXITCODE): $cmd" }
        }
    } finally { Pop-Location }

    if ($manifest.record_history -and (Test-Path (Join-Path $Target 'app.py'))) {
        Push-Location $Target
        try {
            $pkgName = [IO.Path]::GetFileName($Package)
            & py .\app.py record-update --version ([string]$manifest.version) --previous $current --status applied --package $pkgName
            if ($LASTEXITCODE -ne 0) { Fail-Update 'Bot update-history recording failed' }
        } finally { Pop-Location }
    }

    $last = [pscustomobject]@{ backup=$backupDir; target=$Target; bot=$manifest.bot; version=$manifest.version; previous_version=$current; applied_at=(Get-Date).ToString('o') }
    $last | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $Updates 'last_update.json') -Encoding UTF8
    ([pscustomobject]@{status='applied';bot=$manifest.bot;version=$manifest.version;previous_version=$current;package=[IO.Path]::GetFileName($Package);at=(Get-Date).ToString('o') } | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding UTF8
    $dest = Join-Path $Applied ([IO.Path]::GetFileName($Package))
    if ((Resolve-Path $Package).Path -ne $dest) { Move-Item $Package $dest -Force }
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host " UPDATE APPLIED: $($manifest.bot) -> $($manifest.version)" -ForegroundColor Green
    Write-Host " Previous version: $current" -ForegroundColor Green
    Write-Host " Backup: $backupDir" -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "[UPDATE FAILED] $($_.Exception.Message)" -ForegroundColor Red
    try { ([pscustomobject]@{status='failed';package=[IO.Path]::GetFileName($Package);error=$_.Exception.Message;at=(Get-Date).ToString('o') } | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding UTF8 } catch {}
    if ($backupDir -and (Test-Path (Join-Path $backupDir 'rollback.json'))) {
        $sourceErrors = @()
        try {
            $meta = Get-Content (Join-Path $backupDir 'rollback.json') -Raw | ConvertFrom-Json
            foreach ($f in @($meta.files)) {
                try {
                    $dst = Join-Path $meta.target ([string]$f.path)
                    $bak = Join-Path $backupDir ([string]$f.path)
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
                Write-Host '[ROLLBACK] Source files restored automatically.' -ForegroundColor Yellow
            } else {
                Write-Host "[ROLLBACK WARNING] $($sourceErrors.Count) source file(s) could not be restored; continuing to database rollback." -ForegroundColor Yellow
            }
        } catch {
            $sourceErrors += ("rollback metadata/source phase: {0}" -f $_.Exception.Message)
            Write-Host '[ROLLBACK WARNING] Source restore phase had errors; continuing to database rollback.' -ForegroundColor Yellow
        }
        if ($dbBackupFile -and $dbLiveFile -and (Test-Path $dbBackupFile)) {
            try {
                Remove-Item ($dbLiveFile + '-wal') -Force -ErrorAction SilentlyContinue
                Remove-Item ($dbLiveFile + '-shm') -Force -ErrorAction SilentlyContinue
                $restoreCode = 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()'
                if (-not (Invoke-PythonRetry -Arguments @('-c',$restoreCode,$dbBackupFile,$dbLiveFile))) { throw 'SQLite restore command failed' }
                Write-Host '[ROLLBACK] Database restored automatically.' -ForegroundColor Yellow
            } catch { Write-Host "[DATABASE ROLLBACK ERROR] $($_.Exception.Message)" -ForegroundColor Red }
        }
        if ($sourceErrors.Count -gt 0) {
            $sourceErrors | ForEach-Object { Write-Host "[ROLLBACK SOURCE ERROR] $_" -ForegroundColor Red }
        }
    }
    try {
        $dest = Join-Path $Failed ([IO.Path]::GetFileName($Package))
        if (Test-Path $Package) { Move-Item $Package $dest -Force }
    } catch {}
    exit 2
}
finally {
    Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
