param(
    [string]$Root,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'
$expected = 'APPLY_ADMIN_SEPARATION'
if ($Approval -ne $expected) {
    throw "Approval missing. Re-run with -Approval $expected"
}

if (-not $Root) { $Root = (git rev-parse --show-toplevel).Trim() }
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
            $out.Add("$Name=$Value"); $found = $true
        } else { $out.Add($line) }
    }
    if (-not $found) { $out.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($Path, $out, [System.Text.UTF8Encoding]::new($false))
}

function Remove-EnvKeys([string]$Path, [string[]]$Names) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $nameSet = @{}; foreach ($n in $Names) { $nameSet[$n] = $true }
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
Write-Host 'Mode: BACKUP + CONFIG OWNERSHIP + SURGICAL POSTER GUARD'
Write-Host 'Running services: NOT STOPPED / NOT RESTARTED'
Write-Host 'Worker/queue/database/campaigns/sessions: NOT MODIFIED'
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

    Write-Host '[1/5] Backing up separation-sensitive local state...'
    foreach ($rel in @(
        'bots/Smart_Auto_Poster_V2/.env',
        'bots/Smart_Auto_Poster_V2/smart_autoposter/settings.py',
        'bots/Admin_Command_Centre/.env'
    )) {
        $src = Join-Path $Root ($rel -replace '/', '\')
        if (Test-Path -LiteralPath $src) {
            $dst = Join-Path $backup ($rel -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    & git status --porcelain | Set-Content -LiteralPath (Join-Path $backup 'git-status-before.txt') -Encoding UTF8
    & git rev-parse HEAD | Set-Content -LiteralPath (Join-Path $backup 'git-head-before.txt') -Encoding ASCII
    Write-Host "Rollback backup: $backup"

    Write-Host '[2/5] Moving Telegram admin configuration ownership...'
    $posterEnv = Read-EnvMap $posterEnvPath
    $adminEnv = Read-EnvMap $adminEnvPath
    $legacyToken = if ($posterEnv.ContainsKey('ADMIN_BOT_TOKEN')) { $posterEnv['ADMIN_BOT_TOKEN'] } else { '' }
    $legacyUsers = if ($posterEnv.ContainsKey('ADMIN_USER_IDS')) { $posterEnv['ADMIN_USER_IDS'] } else { '' }
    $existingAdminToken = if ($adminEnv.ContainsKey('VM_ADMIN_BOT_TOKEN')) { $adminEnv['VM_ADMIN_BOT_TOKEN'] } else { '' }
    $existingAdminUsers = if ($adminEnv.ContainsKey('VM_ADMIN_USER_IDS')) { $adminEnv['VM_ADMIN_USER_IDS'] } else { '' }

    if ([string]::IsNullOrWhiteSpace($existingAdminToken)) {
        if ([string]::IsNullOrWhiteSpace($legacyToken)) { throw 'No admin bot token found locally. No secret was changed.' }
        Set-EnvValue $adminEnvPath 'VM_ADMIN_BOT_TOKEN' $legacyToken
        Write-Host 'Admin bot token ownership copied to Admin Command Centre: YES'
    } else {
        Write-Host 'Admin Command Centre already has a token: YES'
    }
    if ([string]::IsNullOrWhiteSpace($existingAdminUsers) -and -not [string]::IsNullOrWhiteSpace($legacyUsers)) {
        Set-EnvValue $adminEnvPath 'VM_ADMIN_USER_IDS' $legacyUsers
        Write-Host 'Admin user IDs ownership copied to Admin Command Centre: YES'
    }
    Set-EnvValue $adminEnvPath 'VM_ADMIN_ALLOW_MUTATIONS' 'false'

    Write-Host '[3/5] Forcing only the embedded Smart Auto Poster admin guard off...'
    $settings = [System.IO.File]::ReadAllText($posterSettingsPath)
    if ($settings -match '(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False') {
        Write-Host 'Embedded admin guard already disabled: YES'
    } else {
        $pattern = '(?ms)(@property\s*\r?\n\s*def\s+admin_bot_enabled\s*\(self\)\s*->\s*bool\s*:\s*\r?\n)(.*?)(?=\r?\n\s*def\s+ensure_dirs\s*\()'
        $replacement = '$1        """Embedded admin is disabled; Admin_Command_Centre owns Telegram administration."""' + "`r`n" + '        return False' + "`r`n"
        $patched = [regex]::Replace($settings, $pattern, $replacement, 1)
        if ($patched -eq $settings) { throw 'Could not safely locate admin_bot_enabled; restored nothing and made no fallback rewrite.' }
        [System.IO.File]::WriteAllText($posterSettingsPath, $patched, [System.Text.UTF8Encoding]::new($false))
    }

    Write-Host '[4/5] Removing legacy Smart Auto Poster admin configuration keys...'
    Remove-EnvKeys $posterEnvPath @(
        'ADMIN_BOT_TOKEN','ADMIN_USER_IDS','ADMIN_READONLY_USER_IDS','ADMIN_BOT_SESSION',
        'ADMIN_BOT_PERSIST_SESSION','ADMIN_NOTIFICATIONS_MIN_SEVERITY'
    )

    Write-Host '[5/5] Verifying on-disk separation...'
    $verifySettings = [System.IO.File]::ReadAllText($posterSettingsPath)
    if ($verifySettings -notmatch '(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False') {
        throw 'Verification failed: embedded admin guard is not disabled.'
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
        & $python -3.12 -m py_compile $posterSettingsPath
        if ($LASTEXITCODE -ne 0) { throw 'Patched Smart Auto Poster settings.py failed Python compilation.' }
    }

    Write-Host ''
    Write-Host 'ON-DISK SEPARATION: PASSED' -ForegroundColor Green
    Write-Host 'RUNTIME CUTOVER:     PENDING'
    Write-Host 'Admin mutations:     DISABLED'
    Write-Host ''
    Write-Host 'No running process was stopped or restarted.'
    Write-Host 'The currently loaded embedded admin may remain in memory until Smart Auto Poster is safely restarted.'
    Write-Host 'Do not start another Admin Command Centre instance yet.'
    Write-Host "Rollback backup: $backup"
    Write-Host 'Copy this output back to ChatGPT. Secret values were never printed.'
} finally {
    Pop-Location
}
