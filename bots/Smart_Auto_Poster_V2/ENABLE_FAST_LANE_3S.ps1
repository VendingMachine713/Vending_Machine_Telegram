param(
    [string]$Campaign = 'main_production_01',
    [int]$GapSeconds = 3
)

$ErrorActionPreference = 'Stop'
if ($GapSeconds -lt 2) {
    throw 'GapSeconds must be at least 2. This update will not bypass Telegram rate limits.'
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Find-MasterRoot {
    $candidates = @(
        (Join-Path $env:USERPROFILE 'OneDrive\Desktop\Vending_Machine_Telegram'),
        (Join-Path $env:USERPROFILE 'Desktop\Vending_Machine_Telegram')
    )
    foreach ($p in $candidates) {
        if (Test-Path (Join-Path $p 'bots\Smart_Auto_Poster_V2')) { return $p }
    }

    $found = Get-ChildItem $env:USERPROFILE -Directory -Filter 'Vending_Machine_Telegram' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'bots\Smart_Auto_Poster_V2') } |
        Select-Object -First 1

    if ($found) { return $found.FullName }
    throw 'Could not locate Vending_Machine_Telegram master folder.'
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }

    $pattern = '^\s*' + [Regex]::Escape($Name) + '\s*='
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match $pattern) {
            if (-not $found) {
                "$Name=$Value"
                $found = $true
            }
        } else {
            $line
        }
    }

    if (-not $found) {
        if ($out.Count -gt 0 -and $out[-1] -ne '') { $out += '' }
        $out += "$Name=$Value"
    }

    [IO.File]::WriteAllLines($Path, [string[]]$out, $Utf8NoBom)
}

$Master = Find-MasterRoot
$Bot = Join-Path $Master 'bots\Smart_Auto_Poster_V2'
$Db = Join-Path $Bot 'data\smart_autoposter.sqlite3'
$EnvFile = Join-Path $Bot '.env'

if (-not (Test-Path $Db)) {
    throw "Smart Auto Poster database not found: $Db"
}

Set-Location -LiteralPath $Bot

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - FAST LANE 3s' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Campaign              : $Campaign"
Write-Host "Healthy-lane gap      : $GapSeconds seconds"
Write-Host 'Fresh pending jobs    : FIRST'
Write-Host 'Retry/deferred jobs   : TAIL'
Write-Host 'Sending/UNCERTAIN     : NEVER rewritten'
Write-Host '4-hour schedule       : PRESERVED'
Write-Host 'Telegram rate limits  : RESPECTED'
Write-Host ''

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupRoot = Join-Path $env:LOCALAPPDATA "Vending_Machine_Telegram\fast_lane_backups\SAP_FAST_LANE_$stamp"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$backupHelper = Join-Path $env:TEMP ('sap_fastlane_backup_' + [guid]::NewGuid().ToString('N') + '.py')
@'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src, timeout=60)
s.execute("PRAGMA busy_timeout=60000")
d = sqlite3.connect(dst, timeout=60)
s.backup(d)
d.close()
s.close()
'@ | Set-Content -LiteralPath $backupHelper -Encoding UTF8

try {
    $dbBackup = Join-Path $backupRoot 'smart_autoposter.sqlite3'
    & py $backupHelper $Db $dbBackup
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dbBackup)) {
        throw 'Could not create the Fast Lane database backup.'
    }

    if (Test-Path $EnvFile) {
        Copy-Item -LiteralPath $EnvFile -Destination (Join-Path $backupRoot '.env.backup') -Force
    }

    Write-Host "[OK] Recovery backup: $backupRoot" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $backupHelper -Force -ErrorAction SilentlyContinue
}

$helper = Join-Path $env:TEMP ('sap_fastlane_' + [guid]::NewGuid().ToString('N') + '.py')
@'
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

db_path = Path(sys.argv[1])
campaign_id = sys.argv[2]
gap = max(2, int(sys.argv[3]))

def parse_dt(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None

def iso(d):
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")

now = datetime.now(timezone.utc)

con = sqlite3.connect(db_path, timeout=60)
con.row_factory = sqlite3.Row
con.execute("PRAGMA foreign_keys=ON")
con.execute("PRAGMA busy_timeout=60000")

try:
    integrity = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
    if integrity != ["ok"]:
        raise RuntimeError(f"SQLite integrity failed before Fast Lane change: {integrity}")

    con.execute("BEGIN IMMEDIATE")

    campaign = con.execute(
        "SELECT * FROM campaigns WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()
    if not campaign:
        raise RuntimeError(f"Unknown campaign: {campaign_id}")

    schedule_before = con.execute(
        "SELECT * FROM campaign_schedules WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()

    con.execute(
        "UPDATE campaigns SET spread_seconds=0,updated_at=? WHERE campaign_id=?",
        (iso(now), campaign_id),
    )

    run = con.execute(
        """SELECT run_key,MAX(id) AS max_id,COUNT(*) AS n
           FROM queue
           WHERE campaign_id=?
             AND run_key IS NOT NULL
             AND status IN ('pending','retry','deferred','sending','uncertain')
           GROUP BY run_key
           ORDER BY max_id DESC
           LIMIT 1""",
        (campaign_id,),
    ).fetchone()

    accelerated_pending = 0
    blocked_pending = 0
    tailed_problem_jobs = 0
    untouched_sending = 0
    untouched_uncertain = 0
    active_run = None

    if run:
        active_run = run["run_key"]

        rows = con.execute(
            """SELECT q.id,q.status,q.due_at,q.group_id,
                      d.next_eligible_at,d.quarantine_until,d.consecutive_failures
               FROM queue q
               JOIN destinations d ON d.group_id=q.group_id
               WHERE q.campaign_id=? AND q.run_key=?
                 AND q.status IN ('pending','retry','deferred','sending','uncertain')
               ORDER BY q.id""",
            (campaign_id, active_run),
        ).fetchall()

        clean_pending = []
        blocked = []
        problems = []

        for r in rows:
            status = r["status"]
            if status == "sending":
                untouched_sending += 1
                continue
            if status == "uncertain":
                untouched_uncertain += 1
                continue
            if status in {"retry", "deferred"}:
                problems.append(r)
                continue

            eligible = parse_dt(r["next_eligible_at"])
            quarantine = parse_dt(r["quarantine_until"])
            if (eligible and eligible > now) or (quarantine and quarantine > now):
                blocked.append(r)
            else:
                clean_pending.append(r)

        lane_start = now + timedelta(seconds=2)
        for idx, r in enumerate(clean_pending):
            due = lane_start + timedelta(seconds=idx * gap)
            con.execute(
                """UPDATE queue
                   SET due_at=?,updated_at=?
                   WHERE id=? AND status='pending'""",
                (iso(due), iso(now), int(r["id"])),
            )
            accelerated_pending += 1

        for r in blocked:
            due = parse_dt(r["due_at"]) or now
            eligible = parse_dt(r["next_eligible_at"])
            quarantine = parse_dt(r["quarantine_until"])
            protected_due = max(
                [x for x in (due, eligible, quarantine) if x is not None],
                default=due,
            )
            con.execute(
                """UPDATE queue
                   SET due_at=?,updated_at=?
                   WHERE id=? AND status='pending'""",
                (iso(protected_due), iso(now), int(r["id"])),
            )
            blocked_pending += 1

        tail_start = lane_start + timedelta(seconds=(len(clean_pending) + 2) * gap)
        for idx, r in enumerate(problems):
            existing_due = parse_dt(r["due_at"]) or now
            wanted_tail = tail_start + timedelta(seconds=idx * gap)
            new_due = max(existing_due, wanted_tail)
            con.execute(
                """UPDATE queue
                   SET due_at=?,updated_at=?
                   WHERE id=? AND status IN ('retry','deferred')""",
                (iso(new_due), iso(now), int(r["id"])),
            )
            tailed_problem_jobs += 1

    account_rows = {
        r["account_key"]: dict(r)
        for r in con.execute(
            "SELECT account_key,authorized,telegram_user_id,identity FROM accounts"
        ).fetchall()
    }

    con.commit()

    integrity_after = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
    if integrity_after != ["ok"]:
        raise RuntimeError(f"SQLite integrity failed after Fast Lane change: {integrity_after}")

    schedule_after = con.execute(
        "SELECT * FROM campaign_schedules WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()

    before_sched = dict(schedule_before) if schedule_before else None
    after_sched = dict(schedule_after) if schedule_after else None

    print(json.dumps({
        "ok": True,
        "campaign_id": campaign_id,
        "spread_seconds": 0,
        "gap_seconds": gap,
        "active_run_key": active_run,
        "accelerated_pending": accelerated_pending,
        "protected_pending": blocked_pending,
        "problem_tail_jobs": tailed_problem_jobs,
        "untouched_sending": untouched_sending,
        "untouched_uncertain": untouched_uncertain,
        "accounts": account_rows,
        "schedule_preserved": before_sched == after_sched,
        "schedule": after_sched,
        "integrity": integrity_after,
    }, ensure_ascii=True))
finally:
    con.close()
'@ | Set-Content -LiteralPath $helper -Encoding UTF8

try {
    $raw = @(& py $helper $Db $Campaign $GapSeconds 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $raw | Out-Host
        throw 'Fast Lane database update failed.'
    }

    try {
        $result = (($raw -join "`n") | ConvertFrom-Json)
    }
    catch {
        $raw | Out-Host
        throw 'Fast Lane result could not be parsed.'
    }

    if (-not [bool]$result.ok -or -not [bool]$result.schedule_preserved) {
        throw 'Fast Lane safety verification failed; the production schedule must remain unchanged.'
    }

    Write-Host '[OK] Database Fast Lane profile applied.' -ForegroundColor Green
    Write-Host "  Active run        : $($result.active_run_key)"
    Write-Host "  Healthy accelerated: $($result.accelerated_pending)"
    Write-Host "  Protected pending : $($result.protected_pending)"
    Write-Host "  Problem tail      : $($result.problem_tail_jobs)"
    Write-Host "  Sending untouched : $($result.untouched_sending)"
    Write-Host "  UNCERTAIN untouched: $($result.untouched_uncertain)"
    Write-Host '  Campaign spread   : 0 seconds'
    Write-Host '  Schedule preserved: TRUE'

    Set-EnvValue -Path $EnvFile -Name 'MIN_SEND_GAP_SECONDS' -Value ([string]$GapSeconds)

    $primaryId = $null
    $secondaryId = $null
    if ($result.accounts.primary -and [bool]$result.accounts.primary.authorized) {
        $primaryId = $result.accounts.primary.telegram_user_id
    }
    if ($result.accounts.secondary -and [bool]$result.accounts.secondary.authorized) {
        $secondaryId = $result.accounts.secondary.telegram_user_id
    }

    if ($primaryId) {
        Set-EnvValue -Path $EnvFile -Name 'PRIMARY_STAGING_CHAT_ID' -Value ([string]$primaryId)
        Write-Host "[OK] Primary media cache staging -> own Saved Messages ($primaryId)." -ForegroundColor Green
    } else {
        Write-Host '[WARN] Primary self-staging ID not available; existing PRIMARY_STAGING_CHAT_ID was left unchanged.' -ForegroundColor Yellow
    }

    if ($secondaryId) {
        Set-EnvValue -Path $EnvFile -Name 'SECONDARY_STAGING_CHAT_ID' -Value ([string]$secondaryId)
        Write-Host "[OK] Secondary media cache staging -> own Saved Messages ($secondaryId)." -ForegroundColor Green
    } else {
        Write-Host '[WARN] Secondary self-staging ID not available; existing SECONDARY_STAGING_CHAT_ID was left unchanged.' -ForegroundColor Yellow
    }

    $receiptDir = Join-Path $Bot 'runtime\production'
    New-Item -ItemType Directory -Force -Path $receiptDir | Out-Null
    $receipt = [ordered]@{
        applied_at = (Get-Date).ToUniversalTime().ToString('o')
        campaign_id = $Campaign
        gap_seconds = $GapSeconds
        spread_seconds = 0
        active_run_key = $result.active_run_key
        accelerated_pending = [int]$result.accelerated_pending
        protected_pending = [int]$result.protected_pending
        problem_tail_jobs = [int]$result.problem_tail_jobs
        untouched_sending = [int]$result.untouched_sending
        untouched_uncertain = [int]$result.untouched_uncertain
        four_hour_schedule_preserved = [bool]$result.schedule_preserved
        media_cache_staging_configured = [bool]($primaryId -or $secondaryId)
        backup_path = $backupRoot
    }
    $receiptPath = Join-Path $receiptDir 'fast_lane_3s.json'
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ' FAST LANE 3s ENABLED' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host "Healthy attempts     : ~one every $GapSeconds seconds when Telegram responds promptly"
    Write-Host 'Problem behavior     : retry/deferred moved behind healthy pending work'
    Write-Host 'Slow/Flood limits    : respected; never bypassed'
    Write-Host 'Sending/UNCERTAIN    : never rewritten by this update'
    Write-Host 'Media cache          : self-staging configured for next service start'
    Write-Host '4-hour cadence       : preserved'
    Write-Host "Recovery backup      : $backupRoot"
    Write-Host "Receipt              : $receiptPath"
}
catch {
    Write-Host "[FAST LANE FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[SAFE] Recovery backup is available at: $backupRoot" -ForegroundColor Yellow
    throw
}
finally {
    Remove-Item -LiteralPath $helper -Force -ErrorAction SilentlyContinue
}
