[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Remote = "origin",
    [string]$BranchPrefix = "sync/windows"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE" }
}

function Test-SafeEnvTemplate {
    param([string]$Path)
    $leaf = Split-Path $Path -Leaf
    return $leaf -in @('.env.example', '.env.sample', '.env.template')
}

function Test-SensitivePath {
    param([string]$Path)
    if (Test-SafeEnvTemplate $Path) { return $false }
    $normalized = $Path -replace '\\','/'
    $leaf = Split-Path $normalized -Leaf
    $patterns = @(
        '*.session','*.session-journal','*.sqlite','*.sqlite3','*.db','*.db-wal','*.db-shm',
        '.env','.env.*','*token*.json','*credentials*.json','*client_secret*.json','*.pem','*.key'
    )
    foreach ($pattern in $patterns) {
        if ($normalized -like $pattern -or $leaf -like $pattern) { return $true }
    }
    return $false
}

$root = (Invoke-Git rev-parse --show-toplevel | Select-Object -First 1).Trim()
Set-Location $root

Write-Host "============================================================"
Write-Host " VM WINDOWS -> GITHUB SAFE RECONCILIATION"
Write-Host "============================================================"
Write-Host "Root       : $root"
Write-Host "Mode       : $(if ($Apply) { 'APPLY (safe sync branch)' } else { 'AUDIT ONLY' })"
Write-Host "Remote     : $Remote"
Write-Host ""

Invoke-Git remote get-url $Remote
Invoke-Git fetch $Remote --prune

$current = (Invoke-Git branch --show-current | Select-Object -First 1).Trim()
$status = @(& git status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw "git status failed" }

Write-Host "Current branch : $current"
Write-Host "Changed files  : $($status.Count)"
if ($status.Count) { $status | ForEach-Object { Write-Host "  $_" } }

$trackedSuspicious = @()
foreach ($line in $status) {
    if ($line.Length -lt 4) { continue }
    $path = $line.Substring(3).Trim('"')
    if (Test-SensitivePath $path) { $trackedSuspicious += $path }
}

if ($trackedSuspicious.Count) {
    Write-Warning "Potential runtime/secret files are already tracked or visible to Git:"
    $trackedSuspicious | Sort-Object -Unique | ForEach-Object { Write-Warning "  $_" }
    throw "Refusing to sync until suspicious tracked files are reviewed."
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "AUDIT COMPLETE - no files changed or pushed."
    Write-Host "Run again with -Apply to create a safe sync branch, stage non-ignored changes, scan them, commit, and push."
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$syncBranch = "$BranchPrefix-$stamp"
Invoke-Git switch -c $syncBranch
Invoke-Git add -A

$staged = @(& git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw "Unable to list staged files" }
if (-not $staged.Count) {
    Write-Host "Nothing to sync. Working tree has no non-ignored changes."
    exit 0
}

$badNames = @($staged | Where-Object { Test-SensitivePath $_ })
if ($badNames.Count) {
    & git reset
    Write-Warning "Blocked sensitive/runtime filenames:"
    $badNames | ForEach-Object { Write-Warning "  $_" }
    throw "Safe sync aborted before commit."
}

$diff = (& git diff --cached --no-ext-diff --unified=0) -join "`n"
$secretPatterns = @(
    '(?i)api[_-]?hash\s*[:=]\s*["''][A-Za-z0-9]{20,}',
    '(?i)bot[_-]?token\s*[:=]\s*["''][0-9]{6,}:[A-Za-z0-9_-]{20,}',
    '(?i)(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    '(?i)AKIA[0-9A-Z]{16}'
)
foreach ($pattern in $secretPatterns) {
    if ($diff -match $pattern) {
        & git reset
        throw "Possible credential detected in staged diff. Safe sync aborted before commit."
    }
}

& git diff --cached --check
if ($LASTEXITCODE -ne 0) {
    & git reset
    throw "git diff --cached --check failed. Safe sync aborted before commit."
}

Invoke-Git commit -m "sync: reconcile Windows master source $stamp"
Invoke-Git push -u $Remote $syncBranch

Write-Host ""
Write-Host "SAFE SYNC COMPLETE"
Write-Host "Branch : $syncBranch"
Write-Host "Files  : $($staged.Count)"
Write-Host "No direct push to main was performed."
Write-Host "Runtime/credential filename and staged-content guards passed."
