param(
    [string]$Root,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'
$expected = 'APPLY_ADMIN_SEPARATION'
if ($Approval -ne $expected) {
    throw "Approval missing. Re-run with -Approval $expected"
}

if (-not $Root) {
    $Root = (git rev-parse --show-toplevel).Trim()
}
$Root = (Resolve-Path $Root).Path
$poster = Join-Path $Root 'bots\Smart_Auto_Poster_V2'
$admin = Join-Path $Root 'bots\Admin_Command_Centre'
$posterEnvPath = Join-Path $poster '.env'
$adminEnvPath = Join-Path $admin '.env'
$posterSettingsPath = Join-Path $poster 'smart_autoposter\settings.py'

function Read-EnvMap([string]$Path) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith('#') -or -not $trim.Contains('=')) { continue }
        $parts = $trim.Split('=', 2)
        $map[$parts[0].Trim()] = $parts[1].Trim().Trim('"').Trim("'")
    }
    return $map
}

function Set-EnvValue([string]$Path, [string]$Name, [string]$Value) {
    $lines = if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path) } else { @() }
    $out = New-Object System.Collections.Generic.List[string]
    $found = $false
    foreach ($line in $lines) {
        if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=')) {
            $out.Add("$Name=$Value")
            $found = $true
        } else {
            $out.Add($line)
        }
    }
    if (-not $found) { $out.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($Path, $out, [System.Text.UTF8Encoding]::new($false))
}

function Remove-EnvKeys([string]$Path, [string[]]$Names) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $nameSet = @{}
    foreach ($n in $Names) { $nameSet[$n] = $true }
    $out = foreach ($line in Get-Content -LiteralPath $Path) {
        $trim = $line.Trim()
        if ($trim -and -not $trim.StartsWith('#') -and $trim.Contains('=')) {
            $key = $trim.Split('=', 2)[0].Trim()
            if ($nameSet.ContainsKey($key)) { continue }
        }
        $line
    }
    [System.IO.File]::WriteAllLines($Path, @($out), [System.Text.UTF8Encoding]::new($false))
}

Write-Host '============================================================'
Write-Host ' VM ADMIN / SMART AUTO POSTER - STAGED LOCAL SEPARATION'
Write-Host '============================================================'
Write-Host 'Mode: BACKUP + CONFIG MIGRATION + CODE BOUNDARY PATCH'
Write-Host 'Running services: NOT STOPPED / NOT RESTARTED'
Write-Host 'Campaigns/queues/database/sessions: NOT MODIFIED'
Write-Host "Root: $Root"
Write-Host ''

foreach ($required in @($poster, $admin, $posterSettingsPath, $posterEnvPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required local path missing: $required" }
}

Push-Location $Root
try {
    & git fetch origin main | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'git fetch origin main failed; nothing has been changed.' }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $Root "backups\admin-separation-$stamp"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null

    Write-Host '[1/6] Backing up local separation-sensitive files...'
    $backupItems = @(
        'bots/Smart_Auto_Poster_V2/.env',
        'bots/Smart_Auto_Poster_V2/smart_autoposter/settings.py',
        'bots/Admin_Command_Centre/.env',
        'bots/Admin_Command_Centre/admin_core.py',
        'bots/Admin_Command_Centre/main.py',
        'bots/Admin_Command_Centre/BOT_MANIFEST.json',
        'bots/Admin_Command_Centre/VERSION.txt',
        'bots/Admin_Command_Centre/README.md',
        'bots/Admin_Command_Centre/.env.example',
        'bots/Admin_Command_Centre/START_ADMIN_COMMAND_CENTRE.bat',
        'bots/Admin_Command_Centre/requirements.txt'
    )
    foreach ($rel in $backupItems) {
        $src = Join-Path $Root ($rel -replace '/', '\')
        if (Test-Path -LiteralPath $src) {
            $dst = Join-Path $backup ($rel -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    & git status --porcelain | Set-Content -LiteralPath (Join-Path $backup 'git-status-before.txt') -Encoding UTF8
    & git rev-parse HEAD | Set-Content -LiteralPath (Join-Path $backup 'git-head-before.txt') -Encoding ASCII
    Write-Host "Backup: $backup"

    Write-Host '[2/6] Migrating admin ownership locally (secret values never printed)...'
    $posterEnv = Read-EnvMap $posterEnvPath
    $adminEnv = Read-EnvMap $adminEnvPath
    $legacyToken = if ($posterEnv.ContainsKey('ADMIN_BOT_TOKEN')) { $posterEnv['ADMIN_BOT_TOKEN'] } else { '' }
    $legacyUsers = if ($posterEnv.ContainsKey('ADMIN_USER_IDS')) { $posterEnv['ADMIN_USER_IDS'] } else { '' }
    $existingAdminToken = if ($adminEnv.ContainsKey('VM_ADMIN_BOT_TOKEN')) { $adminEnv['VM_ADMIN_BOT_TOKEN'] } else { '' }
    $existingAdminUsers = if ($adminEnv.ContainsKey('VM_ADMIN_USER_IDS')) { $adminEnv['VM_ADMIN_USER_IDS'] } else { '' }

    if ([string]::IsNullOrWhiteSpace($existingAdminToken)) {
        if ([string]::IsNullOrWhiteSpace($legacyToken)) { throw 'No local admin token was found in either Admin Command Centre or legacy Smart Auto Poster config.' }
        Set-EnvValue $adminEnvPath 'VM_ADMIN_BOT_TOKEN' $legacyToken
    }
    if ([string]::IsNullOrWhiteSpace($existingAdminUsers) -and -not [string]::IsNullOrWhiteSpace($legacyUsers)) {
        Set-EnvValue $adminEnvPath 'VM_ADMIN_USER_IDS' $legacyUsers
    }
    Set-EnvValue $adminEnvPath 'VM_ADMIN_ALLOW_MUTATIONS' 'false'

    Write-Host '[3/6] Installing canonical standalone Admin Command Centre control files from origin/main...'
    $adminFiles = @(
        'admin_core.py','main.py','BOT_MANIFEST.json','VERSION.txt','README.md','.env.example','START_ADMIN_COMMAND_CENTRE.bat','requirements.txt'
    )
    foreach ($name in $adminFiles) {
        $repoPath = "bots/Admin_Command_Centre/$name"
        $content = & git show "origin/main:$repoPath"
        if ($LASTEXITCODE -ne 0) { throw "Could not read $repoPath from origin/main." }
        $destination = Join-Path $admin $name
        [System.IO.File]::WriteAllText($destination, (($content -join "`n") + "`n"), [System.Text.UTF8Encoding]::new($false))
    }

    Write-Host '[4/6] Patching only Smart Auto Poster admin ownership guard...'
    $settings = [System.IO.File]::ReadAllText($posterSettingsPath)
    $pattern = '(?ms)(@property\s*\r?\n\s*def\s+admin_bot_enabled\s*\(self\)\s*->\s*bool\s*:\s*\r?\n)(.*?)(?=\r?\n\s*def\s+ensure_dirs\s*\()'
    $replacement = '$1        """Embedded admin is disabled; Admin_Command_Centre owns Telegram administration."""' + "`r`n" + '        return False' + "`r`n"
    $patched = [regex]::Replace($settings, $pattern, $replacement, 1)
    if ($patched -eq $settings) {
        throw 'Could not safely locate the admin_bot_enabled property in local Smart Auto Poster settings.py; no destructive fallback was attempted.'
    }
    [System.IO.File]::WriteAllText($posterSettingsPath, $patched, [System.Text.UTF8Encoding]::new($false))

    Remove-EnvKeys $posterEnvPath @('ADMIN_BOT_TOKEN','ADMIN_USER_IDS','ADMIN_READONLY_USER_IDS','ADMIN_BOT_SESSION','ADMIN_BOT_PERSIST_SESSION','ADMIN_NOTIFICATIONS_MIN_SEVERITY')

    Write-Host '[5/6] Verifying staged separation...'
    $verifySettings = [System.IO.File]::ReadAllText($posterSettingsPath)
    if ($verifySettings -notmatch '(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False') {
        throw 'Verification failed: embedded admin guard is not forced disabled.'
    }
    $posterAfter = Read-EnvMap $posterEnvPath
    foreach ($key in @('ADMIN_BOT_TOKEN','ADMIN_USER_IDS','ADMIN_BOT_SESSION')) {
        if ($posterAfter.ContainsKey($key) -and -not [string]::IsNullOrWhiteSpace($posterAfter[$key])) {
            throw "Verification failed: legacy poster admin key still active: $key"
        }
    }
    $adminAfter = Read-EnvMap $adminEnvPath
    if (-not $adminAfter.ContainsKey('VM_ADMIN_BOT_TOKEN') -or [string]::IsNullOrWhiteSpace($adminAfter['VM_ADMIN_BOT_TOKEN'])) {
        throw 'Verification failed: Admin Command Centre token is not configured.'
    }

    $python = $null
    try { $python = (Get-Command py.exe -ErrorAction Stop).Source } catch {}
    if ($python) {
        & $python -3.12 -m compileall -q (Join-Path $admin '.') (Join-Path $poster 'smart_autoposter\settings.py')
        if ($LASTEXITCODE -ne 0) { throw 'Python compile verification failed.' }
        Push-Location $admin
        try {
            & $python -3.12 main.py --self-test | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Admin Command Centre self-test failed.' }
        } finally { Pop-Location }
    } else {
        Write-Warning 'py.exe not found; Python compile/self-test skipped.'
    }

    Write-Host '[6/6] Staged migration complete.' -ForegroundColor Green
    Write-Host 'ON-DISK SEPARATION: APPLIED'
    Write-Host 'RUNTIME CUTOVER:     NOT YET APPLIED'
    Write-Host ''
    Write-Host 'IMPORTANT: Running Smart Auto Poster/Admin processes were intentionally left untouched.'
    Write-Host 'The old embedded admin can remain in memory until Smart Auto Poster is safely restarted.'
    Write-Host 'Do not start a second Admin Command Centre process yet.'
    Write-Host "Rollback backup: $backup"
    Write-Host ''
    Write-Host 'Copy this output back to ChatGPT. No secret values are printed.'
} finally {
    Pop-Location
}
