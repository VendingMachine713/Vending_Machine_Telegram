$ErrorActionPreference = 'Continue'
$Bot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Db = Join-Path $Bot 'data\smart_autoposter.sqlite3'
$VersionFile = Join-Path $Bot 'VERSION.txt'
$InitFile = Join-Path $Bot 'smart_autoposter\__init__.py'
$LocalBackupRoot = Join-Path $env:LOCALAPPDATA 'Vending_Machine_Telegram\update_backups'
$LegacyBackupRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $Bot)) 'updates\backups'

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - RECOVERY DOCTOR (READ ONLY)' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Bot folder : $Bot"
Write-Host "Database   : $Db"

$fileVersion = if (Test-Path $VersionFile) { (Get-Content $VersionFile -Raw).Trim() } else { '<missing>' }
$moduleVersion = '<unknown>'
if (Test-Path $InitFile) {
    $line = Get-Content $InitFile | Where-Object { $_ -match '__version__\s*=' } | Select-Object -First 1
    if ($line -match '"([^"]+)"') { $moduleVersion = $Matches[1] }
}
$versionOk = ($fileVersion -ne '<missing>' -and $fileVersion -eq $moduleVersion)
Write-Host ("Version     : VERSION.txt={0} module={1} consistency={2}" -f $fileVersion,$moduleVersion,$versionOk)

if (-not (Test-Path $Db)) {
    Write-Host '[FAIL] Database file is missing.' -ForegroundColor Red
    exit 2
}

$Probe = Join-Path $env:TEMP ('sap_db_probe_' + [guid]::NewGuid().ToString('N') + '.py')
@'
import json, sqlite3, sys
p=sys.argv[1]
r={"path":p,"ok":False,"quick_check":[],"integrity":[],"foreign_key_errors":[],"schema_version":None,"error":None}
try:
    con=sqlite3.connect(p, timeout=60)
    con.execute('PRAGMA busy_timeout=60000')
    r['quick_check']=[x[0] for x in con.execute('PRAGMA quick_check').fetchall()]
    r['integrity']=[x[0] for x in con.execute('PRAGMA integrity_check').fetchall()]
    r['foreign_key_errors']=[list(x) for x in con.execute('PRAGMA foreign_key_check').fetchall()]
    try:
        row=con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        r['schema_version']=row[0] if row else None
    except Exception: pass
    con.close()
    r['ok']=(r['quick_check']==['ok'] and r['integrity']==['ok'] and not r['foreign_key_errors'])
except Exception as e:
    r['error']=f'{type(e).__name__}: {e}'
print(json.dumps(r,ensure_ascii=False))
sys.exit(0 if r['ok'] else 2)
'@ | Set-Content $Probe -Encoding UTF8

$probeResult = $null
for ($i=1; $i -le 3; $i++) {
    try {
        $raw = & py $Probe $Db 2>&1
        $exit = $LASTEXITCODE
        if ($raw) {
            $lastLine = @($raw)[-1]
            try { $probeResult = $lastLine | ConvertFrom-Json } catch {}
        }
        if ($exit -eq 0 -and $probeResult) { break }
    } catch {}
    [GC]::Collect(); [GC]::WaitForPendingFinalizers(); Start-Sleep -Seconds ($i * 2)
}
Remove-Item $Probe -Force -ErrorAction SilentlyContinue

if ($probeResult) {
    Write-Host ("SQLite      : ok={0} quick={1} integrity={2} FK-errors={3} schema={4}" -f $probeResult.ok,($probeResult.quick_check -join ','),($probeResult.integrity -join ','),@($probeResult.foreign_key_errors).Count,$probeResult.schema_version)
    if ($probeResult.error) { Write-Host "DB error     : $($probeResult.error)" -ForegroundColor Red }
} else {
    Write-Host '[FAIL] SQLite probe process could not return a result after 3 attempts.' -ForegroundColor Red
}

Write-Host ''
Write-Host 'Recent rollback snapshots:' -ForegroundColor DarkCyan
$candidates = @()
if (Test-Path $LocalBackupRoot) { $candidates += Get-ChildItem $LocalBackupRoot -Directory -ErrorAction SilentlyContinue }
if (Test-Path $LegacyBackupRoot) { $candidates += Get-ChildItem $LegacyBackupRoot -Directory -ErrorAction SilentlyContinue }
$candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 8 | ForEach-Object {
    $dbb = Join-Path $_.FullName 'database\smart_autoposter.sqlite3'
    Write-Host ("  {0} | DB={1} | {2}" -f $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'),(Test-Path $dbb),$_.FullName)
}

Write-Host ''
if ($versionOk -and $probeResult -and $probeResult.ok) {
    Write-Host '[PASS] Read-only recovery checks are healthy.' -ForegroundColor Green
    exit 0
}
Write-Host '[ATTENTION] Recovery doctor found an inconsistency. Do not start production until repaired.' -ForegroundColor Yellow
exit 2
