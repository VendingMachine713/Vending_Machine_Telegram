param(
    [switch]$SkipDatabase
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "============================================================"
Write-Host " VM UNIVERSAL SEARCH - LOCAL QUALITY GATE"
Write-Host "============================================================"
Write-Host "Safety: compile/tests/read-only DB checks only. No Telegram sends."
Write-Host ""

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "> $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
    Write-Host "[OK] $Name"
}

Invoke-Step "Compile Universal Search" {
    & py -m compileall -q .
}

Invoke-Step "Run Universal Search tests" {
    & py -m unittest discover -s tests -p 'test_*.py' -v
}

Write-Host "> Parse PowerShell launchers"
$PowerShellFiles = @(
    '.\START.ps1',
    '.\BACKFILL.ps1',
    '.\MARKETPLACE.ps1',
    '.\MATCH_ENGINE.ps1',
    '.\RUN_MATCH_ENGINE.ps1',
    '.\INSTALL_MATCH_ENGINE_AUTOSTART.ps1',
    '.\VALIDATE.ps1'
)
foreach ($file in $PowerShellFiles) {
    if (-not (Test-Path $file)) {
        throw "Required PowerShell file missing: $file"
    }
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path $file), [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -gt 0) {
        $errors | ForEach-Object { Write-Error ("{0}: {1}" -f $file, $_.Message) }
        throw "PowerShell parsing failed: $file"
    }
}
Write-Host "[OK] PowerShell launchers parse cleanly"

if (-not $SkipDatabase) {
    Write-Host "> Read-only local database integrity check"
    $Db = Join-Path $PSScriptRoot 'data\universal_search.db'
    if (Test-Path $Db) {
        $DbEscaped = $Db.Replace("'", "''")
        $Python = @"
import sqlite3
path = r'''$DbEscaped'''
con = sqlite3.connect(path, timeout=10)
try:
    integrity = con.execute('PRAGMA integrity_check').fetchall()
    fk = con.execute('PRAGMA foreign_key_check').fetchall()
finally:
    con.close()
print({'integrity': [r[0] for r in integrity], 'foreign_key_errors': fk})
if integrity != [('ok',)] or fk:
    raise SystemExit(2)
"@
        $Python | & py -
        if ($LASTEXITCODE -ne 0) {
            throw "Database integrity check failed."
        }
        Write-Host "[OK] Local database integrity"
    }
    else {
        Write-Host "[INFO] No local database exists yet; DB integrity check skipped."
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host " UNIVERSAL SEARCH QUALITY GATE PASSED"
Write-Host "============================================================"
