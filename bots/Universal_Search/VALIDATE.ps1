param(
    [switch]$SkipDatabase
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "============================================================"
Write-Host " VM UNIVERSAL SEARCH v1.6 - LOCAL QUALITY GATE"
Write-Host "============================================================"
Write-Host "Safety: compile/tests/temp-schema/read-only DB checks only. No Telegram sends."
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

Write-Host "> Validate BOT_MANIFEST.json"
$manifest = Get-Content '.\BOT_MANIFEST.json' -Raw | ConvertFrom-Json
if (-not $manifest.name -or $manifest.name -ne 'Universal_Search') {
    throw 'BOT_MANIFEST.json has an unexpected bot name.'
}
if ($manifest.version -ne '1.6.0') {
    throw "BOT_MANIFEST.json expected version 1.6.0, found $($manifest.version)."
}
$RequiredCapabilities = @(
    'event_driven_two_way_matching',
    'sql_candidate_prefiltering',
    'candidate_window_safe_revalidation',
    'wtb_expiry_reminders',
    'historical_wtb_reminder_baseline',
    'advisory_match_threshold_calibration',
    'admin_match_commands'
)
foreach ($capability in $RequiredCapabilities) {
    if ($manifest.capabilities -notcontains $capability) {
        throw "BOT_MANIFEST.json missing v1.6 capability: $capability"
    }
}
Write-Host ("[OK] BOT_MANIFEST.json name={0} version={1}" -f $manifest.name, $manifest.version)

Write-Host "> Validate required v1.6 files"
$RequiredFiles = @(
    '.\match_engine_v2.py',
    '.\match_engine_v2_runtime.py',
    '.\match_daemon_v2.py',
    '.\match_cli_v2.py',
    '.\match_commands_v2.py',
    '.\match_ui_v2.py',
    '.\migrations\__init__.py',
    '.\migrations\0007_match_feedback.py',
    '.\tests\test_match_engine_v2.py',
    '.\tests\test_match_engine_v2_backfill.py',
    '.\tests\test_match_engine_v2_candidate_window.py'
)
foreach ($file in $RequiredFiles) {
    if (-not (Test-Path $file)) {
        throw "Required v1.6 file missing: $file"
    }
}
Write-Host "[OK] Required v1.6 files present"

Invoke-Step "Match Engine v2 temporary-schema smoke check" {
    $Python = @'
import sqlite3
import tempfile
from pathlib import Path
from core import Store
from marketplace import MarketplaceStore
from match_engine_v2_runtime import HardenedMatchEngineV2

with tempfile.TemporaryDirectory() as d:
    db = Path(d) / 'quality_gate.db'
    Store(db)
    MarketplaceStore(db)
    HardenedMatchEngineV2(db)
    con = sqlite3.connect(db)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        required_tables = {
            'marketplace_matches',
            'marketplace_match_feedback',
            'marketplace_match_events',
            'marketplace_wtb_expiry',
            'marketplace_wtb_expiry_alert_queue',
            'marketplace_match_v2_state',
        }
        required_triggers = {
            'marketplace_match_event_ai',
            'marketplace_match_event_au',
            'marketplace_match_event_bd',
        }
        missing_tables = sorted(required_tables - tables)
        missing_triggers = sorted(required_triggers - triggers)
        integrity = con.execute('PRAGMA integrity_check').fetchall()
    finally:
        con.close()
    if missing_tables or missing_triggers or integrity != [('ok',)]:
        raise SystemExit({
            'missing_tables': missing_tables,
            'missing_triggers': missing_triggers,
            'integrity': integrity,
        })
    print({'tables': len(tables), 'triggers': len(triggers), 'integrity': 'ok'})
'@
    $Python | & py -
}

Write-Host "> Parse PowerShell launchers"
$PowerShellFiles = @(
    '.\START.ps1',
    '.\BACKFILL.ps1',
    '.\MARKETPLACE.ps1',
    '.\MATCH_ENGINE.ps1',
    '.\RUN_MATCH_ENGINE.ps1',
    '.\MATCH_ENGINE_STATUS.ps1',
    '.\INSTALL_MATCH_ENGINE_AUTOSTART.ps1',
    '.\UNINSTALL_MATCH_ENGINE_AUTOSTART.ps1',
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
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
finally:
    con.close()
print({'integrity': [r[0] for r in integrity], 'foreign_key_errors': fk, 'tables': len(tables)})
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
Write-Host " UNIVERSAL SEARCH v1.6 QUALITY GATE PASSED"
Write-Host "============================================================"
