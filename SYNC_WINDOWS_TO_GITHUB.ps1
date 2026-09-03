[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Remote = "origin",
    [string]$BranchPrefix = "sync/windows"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & git @Args
    if ($LASTEXITCODE -ne 0) { throw "git $($Args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Find-Python {
    foreach ($candidate in @("py", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    throw "Python was not found on PATH."
}

$root = (Invoke-Git rev-parse --show-toplevel | Select-Object -First 1).Trim()
Set-Location $root
$python = Find-Python
$guard = Join-Path $root "tools\vm_core\git\git_guard.py"
$sourceReport = Join-Path $root "tools\ci\source_of_truth_report.py"
$snapshotTool = Join-Path $root "tools\ci\create_source_snapshot.py"
$stagedPolicy = Join-Path $root "tools\ci\staged_source_policy.py"

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

if (Test-Path $sourceReport) {
    Write-Host ""
    Write-Host "[AUDIT] Source-of-truth report"
    & $python $sourceReport
    if ($LASTEXITCODE -ne 0) { throw "Source-of-truth report failed." }
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "AUDIT COMPLETE - no files changed, committed or pushed."
    Write-Host "Apply mode creates a safety snapshot and a private reconciliation branch; it never pushes directly to main."
    exit 0
}

if (-not (Test-Path $guard)) { throw "Missing Git secret guard: $guard" }

Write-Host ""
Write-Host "[SAFETY] Scanning all trackable files before any commit..."
& $python $guard
if ($LASTEXITCODE -ne 0) {
    throw "Secret guard blocked reconciliation before staging."
}

if (Test-Path $snapshotTool) {
    Write-Host ""
    Write-Host "[SAFETY] Creating source-only local snapshot with SHA-256 manifest..."
    & $python $snapshotTool
    if ($LASTEXITCODE -ne 0) { throw "Source safety snapshot failed; no commit was attempted." }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$syncBranch = "$BranchPrefix-$stamp"
Write-Host ""
Write-Host "[BRANCH] Creating isolated reconciliation branch: $syncBranch"
Invoke-Git switch -c $syncBranch

# Stage all non-ignored work first so deletes/renames are represented correctly. The
# source-policy step immediately unstages generated/runtime paths while preserving them
# on disk. Secret-like paths remain a hard blocker.
Invoke-Git add -A

if (Test-Path $stagedPolicy) {
    Write-Host "[POLICY] Removing generated/runtime paths from the staged source snapshot..."
    & $python $stagedPolicy --unstage-generated
    if ($LASTEXITCODE -ne 0) {
        & git reset | Out-Null
        throw "Sensitive staged filename detected. Safe sync aborted before commit."
    }
}

$staged = @(& git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw "Unable to list staged files" }
if (-not $staged.Count) {
    Write-Host "Nothing source-like remains to sync after safety policy filtering."
    exit 0
}

Write-Host "[SECURITY] Scanning staged file contents..."
& $python $guard --staged
if ($LASTEXITCODE -ne 0) {
    & git reset | Out-Null
    throw "Safe sync aborted: staged secret guard failed."
}

& git diff --cached --check
if ($LASTEXITCODE -ne 0) {
    & git reset | Out-Null
    throw "git diff --cached --check failed. Safe sync aborted before commit."
}

Invoke-Git commit -m "sync: surface Windows master source $stamp"
Invoke-Git push -u $Remote $syncBranch

$head = (Invoke-Git rev-parse HEAD | Select-Object -First 1).Trim()
$result = @"
VM WINDOWS -> GITHUB SAFE SYNC COMPLETE
Branch: $syncBranch
Commit: $head
Staged source files: $($staged.Count)
Direct push to main: NO
Generated/runtime paths: excluded from staged commit where policy tooling is available
Secret guard: PASSED
Next step: remote reconciliation/review before any merge to main
"@

$downloads = Join-Path $env:USERPROFILE "Downloads"
if (Test-Path $downloads) {
    $resultPath = Join-Path $downloads "VM_GITHUB_SYNC_RESULT.txt"
    $result | Set-Content -Path $resultPath -Encoding UTF8
    Write-Host "Result     : $resultPath"
}

Write-Host ""
Write-Host $result
