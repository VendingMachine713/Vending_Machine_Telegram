param(
    [string]$Root
)

$ErrorActionPreference = 'Stop'

function Get-EnvMap {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction Stop) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith('#') -or -not $trim.Contains('=')) { continue }
        $parts = $trim.Split('=', 2)
        $map[$parts[0].Trim()] = $parts[1].Trim().Trim('"').Trim("'")
    }
    return $map
}

function BoolText([bool]$Value) {
    if ($Value) { return 'YES' }
    return 'NO'
}

if (-not $Root) {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
} else {
    $Root = (Resolve-Path $Root).Path
}

$poster = Join-Path $Root 'bots\Smart_Auto_Poster_V2'
$admin = Join-Path $Root 'bots\Admin_Command_Centre'
$posterEnvPath = Join-Path $poster '.env'
$adminEnvPath = Join-Path $admin '.env'
$posterSettingsPath = Join-Path $poster 'smart_autoposter\settings.py'
$adminVersionPath = Join-Path $admin 'VERSION.txt'

Write-Host '============================================================'
Write-Host ' VM ADMIN / SMART AUTO POSTER SEPARATION AUDIT'
Write-Host '============================================================'
Write-Host 'Mode: READ-ONLY / NON-DESTRUCTIVE'
Write-Host "Root: $Root"
Write-Host ''

$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

Write-Host '[1/6] Git state'
if (Test-Path (Join-Path $Root '.git')) {
    Push-Location $Root
    try {
        $branch = (& git branch --show-current 2>$null).Trim()
        $head = (& git rev-parse --short HEAD 2>$null).Trim()
        $dirty = @(& git status --porcelain 2>$null)
        Write-Host "Branch: $branch"
        Write-Host "HEAD:   $head"
        Write-Host "Dirty:  $(BoolText ($dirty.Count -gt 0))"
        if ($dirty.Count -gt 0) {
            $warnings.Add('Working tree has local changes. Do not pull/reset until those changes are reconciled or backed up.')
        }
    } finally {
        Pop-Location
    }
} else {
    $warnings.Add('Project root is not a Git working tree.')
}
Write-Host ''

Write-Host '[2/6] Canonical folders'
foreach ($path in @($poster, $admin)) {
    $exists = Test-Path -LiteralPath $path -PathType Container
    Write-Host "$(Split-Path $path -Leaf): $(BoolText $exists)"
    if (-not $exists) { $failures.Add("Missing bot folder: $path") }
}
if (Test-Path $adminVersionPath) {
    Write-Host "Admin Command Centre version: $((Get-Content $adminVersionPath -Raw).Trim())"
}
Write-Host ''

Write-Host '[3/6] Smart Auto Poster embedded-admin guard'
$guarded = $false
if (Test-Path $posterSettingsPath) {
    $settings = Get-Content -LiteralPath $posterSettingsPath -Raw
    $match = [regex]::Match($settings, 'def\s+admin_bot_enabled[\s\S]{0,900}?return\s+False')
    $guarded = $match.Success
}
Write-Host "Embedded admin forced disabled: $(BoolText $guarded)"
if (-not $guarded) {
    $failures.Add('Smart Auto Poster does not contain the canonical admin_bot_enabled -> return False guard. This may be a newer snapshot/v6 branch that still needs reconciliation.')
}
Write-Host ''

Write-Host '[4/6] Local configuration ownership (values are NEVER printed)'
$posterEnv = Get-EnvMap $posterEnvPath
$adminEnv = Get-EnvMap $adminEnvPath
$legacyKeys = @('ADMIN_BOT_TOKEN','ADMIN_USER_IDS','ADMIN_READONLY_USER_IDS','ADMIN_BOT_SESSION','ADMIN_BOT_PERSIST_SESSION')
$legacyPresent = @($legacyKeys | Where-Object { $posterEnv.ContainsKey($_) -and -not [string]::IsNullOrWhiteSpace($posterEnv[$_]) })
$adminTokenConfigured = $adminEnv.ContainsKey('VM_ADMIN_BOT_TOKEN') -and -not [string]::IsNullOrWhiteSpace($adminEnv['VM_ADMIN_BOT_TOKEN'])
$adminUsersConfigured = $adminEnv.ContainsKey('VM_ADMIN_USER_IDS') -and -not [string]::IsNullOrWhiteSpace($adminEnv['VM_ADMIN_USER_IDS'])
Write-Host "Smart Auto Poster legacy ADMIN_* values present: $(BoolText ($legacyPresent.Count -gt 0))"
Write-Host "Admin Command Centre token configured:         $(BoolText $adminTokenConfigured)"
Write-Host "Admin Command Centre admin IDs configured:     $(BoolText $adminUsersConfigured)"
if ($legacyPresent.Count -gt 0) {
    $warnings.Add('Smart Auto Poster .env still contains legacy embedded-admin values: ' + ($legacyPresent -join ', ') + '. Do not paste them into chat. They should be migrated/removed only after live reconciliation.')
}
if (-not $adminTokenConfigured) {
    $warnings.Add('Admin Command Centre has no VM_ADMIN_BOT_TOKEN configured locally.')
}
if ($posterEnv.ContainsKey('ADMIN_BOT_TOKEN') -and $adminEnv.ContainsKey('VM_ADMIN_BOT_TOKEN')) {
    $a = $posterEnv['ADMIN_BOT_TOKEN']
    $b = $adminEnv['VM_ADMIN_BOT_TOKEN']
    if (-not [string]::IsNullOrWhiteSpace($a) -and -not [string]::IsNullOrWhiteSpace($b)) {
        Write-Host "Poster/Admin Centre token collision:           $(BoolText ($a -eq $b))"
        if ($a -eq $b) {
            $failures.Add('Smart Auto Poster legacy ADMIN_BOT_TOKEN and Admin Command Centre VM_ADMIN_BOT_TOKEN are the same token. One Telegram bot identity is still shared across both configs.')
        }
    }
}
Write-Host ''

Write-Host '[5/6] Running relevant processes'
$processes = @()
try {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$|^py\.exe$|^powershell\.exe$|^pwsh\.exe$' -and
        $_.CommandLine -and
        ($_.CommandLine -match 'Smart_Auto_Poster_V2|smart_autoposter|Admin_Command_Centre')
    })
} catch {
    $warnings.Add('Could not inspect Windows process command lines: ' + $_.Exception.Message)
}
if ($processes.Count -eq 0) {
    Write-Host 'No matching running processes detected.'
} else {
    foreach ($p in $processes) {
        $role = if ($p.CommandLine -match 'Admin_Command_Centre') { 'ADMIN_COMMAND_CENTRE' } elseif ($p.CommandLine -match 'Smart_Auto_Poster_V2|smart_autoposter') { 'SMART_AUTO_POSTER' } else { 'RELATED' }
        Write-Host ("PID {0,-7} {1,-22} {2}" -f $p.ProcessId, $role, $p.Name)
    }
}
Write-Host ''

Write-Host '[6/6] Result'
if ($failures.Count -eq 0) {
    Write-Host 'SEPARATION STATUS: CODE/CONFIG AUDIT PASSED' -ForegroundColor Green
} else {
    Write-Host 'SEPARATION STATUS: ATTENTION REQUIRED' -ForegroundColor Red
}

if ($warnings.Count -gt 0) {
    Write-Host ''
    Write-Host 'WARNINGS:' -ForegroundColor Yellow
    foreach ($item in $warnings) { Write-Host " - $item" }
}
if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host 'FAILURES:' -ForegroundColor Red
    foreach ($item in $failures) { Write-Host " - $item" }
}

Write-Host ''
Write-Host 'No files, services, tokens, sessions, campaigns, queues, or Git refs were modified.'
Write-Host 'Copy this audit output back to ChatGPT. It contains configuration presence only, not secret values.'

if ($failures.Count -gt 0) { exit 2 }
exit 0
