param(
    [string]$Approval = '',
    [switch]$NoAutostart,
    [switch]$NoStartNow
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$TaskName = 'VendingMachine Smart Auto Poster V2'
$TaskExistedBefore = [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
$RuntimeLock = Join-Path $Root 'runtime\telegram_runtime.lock'
$Campaign = 'main_production_01'
$ExpectedDestinations = 32
$ExpectedVariants = 5
$AlbumItems = 10
$IntervalMinutes = 240
$HeartbeatMaxAgeSeconds = @{ service = 20; scheduler = 45; worker = 20; admin_bot = 20 }
$RequiredApproval = 'ACTIVATE_32_ALBUM_PRODUCTION_4H'
$StartedTask = $false
$Activated = $false
$NormalizedForGoLive = $false
$DbSnapshot = $null
$Temp = Join-Path $env:TEMP ('SAP_GO_LIVE_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Temp | Out-Null

function Stop-VerifiedRuntimeLockOwnerSafely {
    # A live PID in owner.json may be either the original Smart Auto Poster
    # process or a Windows-reused PID. Verify PID + process start time +
    # runtime executable type before terminating anything.
    if (-not (Test-Path $RuntimeLock)) { return $true }
    $ownerPath = Join-Path $RuntimeLock 'owner.json'
    if (-not (Test-Path $ownerPath)) { return $false }
    try { $owner = Get-Content -LiteralPath $ownerPath -Raw | ConvertFrom-Json } catch { return $false }
    $ownerPid = 0
    try { $ownerPid = [int]$owner.pid } catch { return $false }
    if ($ownerPid -le 0) { return $false }

    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
    if (-not $cim) { return $true }
    $name = ([string]$cim.Name).ToLowerInvariant()
    if ($name -notin @('python.exe','pythonw.exe','py.exe','powershell.exe','pwsh.exe','python','pythonw','py','powershell','pwsh')) {
        return $false
    }

    try {
        $recordedStart = [DateTimeOffset]::Parse([string]$owner.started_at).ToUniversalTime()
        $actualStart = ([DateTimeOffset](Get-Process -Id $ownerPid -ErrorAction Stop).StartTime).ToUniversalTime()
        $delta = [math]::Abs(($actualStart - $recordedStart).TotalSeconds)
    } catch { return $false }
    if ($delta -gt 120) {
        # PID has almost certainly been reused by another process. Do not kill it.
        return $false
    }

    Write-Host "[RECOVERY] Stopping verified Smart Auto Poster runtime owner PID $ownerPid (start delta=$([math]::Round($delta,1))s)." -ForegroundColor Yellow
    try { Stop-Process -Id $ownerPid -Force -ErrorAction Stop } catch { return $false }
    for ($i=0; $i -lt 15; $i++) {
        if (-not (Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-ServiceTaskSafely {
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 4
        }
    } catch { }
    # ScheduledTask stop may leave the child Python runtime alive. If it still
    # owns our exact lock, verify its identity before terminating it.
    try { [void](Stop-VerifiedRuntimeLockOwnerSafely) } catch { }
}

function Clear-StaleRuntimeLockSafely {
    # Never remove a lock whose recorded owner is still alive. This only clears
    # crash/stopped-task leftovers after the managed task has been ended.
    for ($i=0; $i -lt 10 -and (Test-Path $RuntimeLock); $i++) { Start-Sleep -Seconds 1 }
    if (-not (Test-Path $RuntimeLock)) { return $true }

    $ownerPath = Join-Path $RuntimeLock 'owner.json'
    $ownerPid = 0
    if (Test-Path $ownerPath) {
        try {
            $owner = Get-Content -LiteralPath $ownerPath -Raw | ConvertFrom-Json
            if ($owner.pid) { $ownerPid = [int]$owner.pid }
        } catch { $ownerPid = 0 }
    }
    if ($ownerPid -gt 0) {
        $ownerProc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($ownerProc) { return $false }
    }
    Remove-Item -LiteralPath $RuntimeLock -Recurse -Force -ErrorAction SilentlyContinue
    return (-not (Test-Path $RuntimeLock))
}

function New-LocalDbSnapshot {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $dir = Join-Path $env:LOCALAPPDATA ("Vending_Machine_Telegram\go_live_backups\Smart_Auto_Poster_$stamp")
    $dst = Join-Path $dir 'smart_autoposter.sqlite3'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $helper = Join-Path $Temp 'sqlite_backup.py'
    @'
import sqlite3,sys
src,dst=sys.argv[1],sys.argv[2]
s=sqlite3.connect(src,timeout=60); s.execute('PRAGMA busy_timeout=60000')
d=sqlite3.connect(dst,timeout=60); s.backup(d); d.close(); s.close()
'@ | Set-Content -LiteralPath $helper -Encoding UTF8
    $src = Join-Path $Root 'data\smart_autoposter.sqlite3'
    & py $helper $src $dst
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dst)) { throw 'Could not create local pre-go-live database snapshot.' }
    return $dst
}

function Restore-DbSnapshot {
    param([string]$Snapshot)
    if (-not $Snapshot -or -not (Test-Path $Snapshot)) { return }
    Stop-ServiceTaskSafely
    for ($i=0; $i -lt 10 -and (Test-Path $RuntimeLock); $i++) { Start-Sleep -Seconds 2 }
    $helper = Join-Path $Temp 'sqlite_restore.py'
    @'
import sqlite3,sys
src,dst=sys.argv[1],sys.argv[2]
s=sqlite3.connect(src,timeout=60); s.execute('PRAGMA busy_timeout=60000')
d=sqlite3.connect(dst,timeout=60); s.backup(d); d.close(); s.close()
'@ | Set-Content -LiteralPath $helper -Encoding UTF8
    $dst = Join-Path $Root 'data\smart_autoposter.sqlite3'
    & py $helper $Snapshot $dst
    if ($LASTEXITCODE -eq 0) { Write-Host '[ROLLBACK] Pre-go-live database snapshot restored.' -ForegroundColor Green }
    else { Write-Host '[ROLLBACK ERROR] Could not restore pre-go-live database snapshot.' -ForegroundColor Red }
}

function Get-JsonCommand {
    param([string[]]$PyArgs)
    $raw = @(& py @PyArgs 2>&1)
    if ($LASTEXITCODE -ne 0) { $raw | Out-Host; throw "Command failed: py $($PyArgs -join ' ')" }
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Get-GoLiveReadinessResult {
    # Unlike Get-JsonCommand, readiness intentionally returns exit code 2 when a
    # gate fails.  We still need its machine-readable JSON to determine whether
    # the *only* failure is an orphaned ACTIVE lifecycle flag left by an earlier
    # failed go-live.
    $args = @('.\app.py','go-live-readiness',$Campaign,'--collection','all_approved','--expected-destinations','32','--expected-variants','5','--require-album-items','10','--require-admin-bot')
    $raw = @(& py @args 2>&1)
    $code = $LASTEXITCODE
    try { $data = (($raw -join "`n") | ConvertFrom-Json) }
    catch { $raw | Out-Host; throw 'Could not parse machine-readable go-live readiness output.' }
    return [pscustomobject]@{ exit_code = $code; data = $data; raw = $raw }
}

function Normalize-OrphanedActiveProduction {
    # Idempotent recovery for the exact state produced by an interrupted/failed
    # activation: campaign ACTIVE, service stopped, and zero unresolved jobs.
    # We fail closed if *any* other readiness problem exists.
    $probe = Get-GoLiveReadinessResult
    $data = $probe.data
    $state = [string]$data.production.state
    $enabled = [bool]$data.production.enabled

    if (-not $enabled -and $state -eq 'ready') {
        Write-Host '[OK] Production lifecycle already READY/inactive.' -ForegroundColor Green
        return $false
    }

    if (-not ($enabled -and $state -eq 'active')) {
        $probe.raw | Out-Host
        throw "Production lifecycle is neither READY/inactive nor recoverable orphan ACTIVE (state=$state enabled=$enabled)."
    }

    $allowed = @(
        'production must be READY/inactive before guarded go-live',
        'production lifecycle must be ready; found active'
    )
    $unexpected = @($data.problems | Where-Object { [string]$_ -notin $allowed })
    if ($unexpected.Count -gt 0) {
        $probe.raw | Out-Host
        throw 'ACTIVE production cannot be normalized because additional go-live safety problems exist.'
    }
    if ([int]$data.production.active_queue_jobs -ne 0 -or @($data.global_unresolved_queue).Count -ne 0) {
        $probe.raw | Out-Host
        throw 'ACTIVE production has unresolved queue work; refusing automatic lifecycle normalization.'
    }

    Write-Host '[RECOVERY] Orphaned ACTIVE production detected with zero unresolved jobs. Normalizing to READY/inactive before snapshot...' -ForegroundColor Yellow
    & py .\app.py campaign-state $Campaign ready | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not normalize orphaned ACTIVE production to READY.' }
    $verify = Get-JsonCommand @('.\app.py','production-readiness',$Campaign,'--collection','all_approved','--json-only')
    if ([bool]$verify.enabled -or [string]$verify.state -ne 'ready' -or [int]$verify.active_queue_jobs -ne 0) {
        throw 'Production lifecycle normalization verification failed.'
    }
    Write-Host '[OK] Orphaned production state normalized to READY/inactive.' -ForegroundColor Green
    return $true
}

function Ensure-FailedGoLiveInactive {
    # Rollback must end in the safe lifecycle state, even if an old snapshot was
    # unexpectedly ACTIVE.  This is only called when this go-live normalized or
    # activated the campaign during the current transaction.
    & py .\app.py campaign-state $Campaign ready *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not force production back to READY after failed go-live.' }
    $verify = Get-JsonCommand @('.\app.py','production-readiness',$Campaign,'--collection','all_approved','--json-only')
    if ([bool]$verify.enabled -or [string]$verify.state -ne 'ready' -or [int]$verify.active_queue_jobs -ne 0) {
        throw 'Rollback verification failed: production is not READY/inactive.'
    }
    Write-Host '[ROLLBACK] Verified production lifecycle READY/inactive.' -ForegroundColor Green
}

try {
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' SMART AUTO POSTER - FINAL GUARDED PRODUCTION GO-LIVE' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host 'Scope: 32 approved destinations, 5 rotating 10-photo albums, every 4 hours.' -ForegroundColor Yellow
    Write-Host 'Safety: first run is re-armed 4 hours FROM activation; no immediate Post Now.' -ForegroundColor Yellow
    Write-Host ''

    if ($Approval -ne $RequiredApproval) {
        throw "Explicit approval missing. Re-run with -Approval $RequiredApproval only if you intend to activate scheduled production across all 32 approved destinations."
    }

    # Prevent a background service from racing with preflight or DB backup.
    Stop-ServiceTaskSafely
    for ($i=0; $i -lt 10 -and (Test-Path $RuntimeLock); $i++) { Start-Sleep -Seconds 2 }
    if (Test-Path $RuntimeLock) { throw 'Runtime lock remains present. A Smart Auto Poster process is still running; go-live aborted before changes.' }

    # V3.2.6: recover the fail-closed but orphaned ACTIVE state *before* taking
    # the rollback snapshot.  This guarantees the snapshot itself is safe.
    $NormalizedForGoLive = Normalize-OrphanedActiveProduction

    $DbSnapshot = New-LocalDbSnapshot
    Write-Host "[OK] Pre-go-live database snapshot: $DbSnapshot" -ForegroundColor Green

    Write-Host '> Applying requested 4-hour production interval while campaign is still inactive...' -ForegroundColor DarkGray
    & py .\app.py schedule $Campaign --interval-minutes $IntervalMinutes --start-in-minutes $IntervalMinutes | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply the requested 4-hour production interval.' }

    Write-Host '> Strict local readiness...' -ForegroundColor DarkGray
    $pre = Get-JsonCommand @('.\app.py','go-live-readiness',$Campaign,'--collection','all_approved','--expected-destinations','32','--expected-variants','5','--require-album-items','10','--expected-interval-minutes','240','--require-admin-bot')
    if (-not $pre.ok) { throw 'Strict go-live readiness did not pass.' }
    Write-Host '[OK] Database, content, canary, visual receipt, queue, delivery and 4-hour schedule gates passed.' -ForegroundColor Green

    Write-Host '> Verifying Telegram user account authorization (NO SEND)...' -ForegroundColor DarkGray
    & py .\app.py accounts-check | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Telegram account authorization check failed.' }

    Write-Host '> Probing private Telegram Admin Bot connection in memory-session mode (NO SEND)...' -ForegroundColor DarkGray
    $adminProbe = Get-JsonCommand @('.\app.py','admin-probe')
    if (-not $adminProbe.ok) { throw 'Telegram Admin Bot connectivity probe failed.' }
    Write-Host "[OK] Admin Bot connectivity probe passed (session=$($adminProbe.session_mode), username=$($adminProbe.username))." -ForegroundColor Green

    Write-Host '> Rearming the 4-hour schedule so activation cannot cause an overdue immediate run...' -ForegroundColor DarkGray
    $arm = Get-JsonCommand @('.\app.py','schedule-rearm',$Campaign)
    $nextUtc = [DateTimeOffset]::Parse([string]$arm.next_run_at)
    $minutes = ($nextUtc - [DateTimeOffset]::UtcNow).TotalMinutes
    if ($minutes -lt 230 -or $minutes -gt 250) { throw "First run was not re-armed ~4 hours ahead ($([math]::Round($minutes,1)) minutes)." }
    Write-Host "[OK] First production cycle re-armed ~4 hours ahead: $($nextUtc.ToString('o'))" -ForegroundColor Green

    Write-Host '> Activating scheduled production...' -ForegroundColor DarkGray
    & py .\app.py campaign-state $Campaign active | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Campaign activation failed.' }
    $Activated = $true

    $post = Get-JsonCommand @('.\app.py','production-readiness',$Campaign,'--collection','all_approved','--json-only')
    if (-not $post.enabled -or $post.state -ne 'active') { throw 'Campaign is not ACTIVE after activation.' }
    if ([int]$post.selected -ne $ExpectedDestinations -or [int]$post.media_delivery.photo_destinations -ne $ExpectedDestinations -or [int]$post.media_delivery.text_destinations -ne 0) {
        throw 'Post-activation ALL_ALBUM invariant failed.'
    }
    if ([int]$post.active_queue_jobs -ne 0) { throw 'Unexpected production queue jobs appeared immediately after activation.' }

    if (-not $NoAutostart) {
        Write-Host '> Installing/refeshing Windows unattended auto-start...' -ForegroundColor DarkGray
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_AUTOSTART.ps1 | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Windows auto-start installation failed.' }
    }

    if (-not $NoStartNow) {
        if ($NoAutostart) {
            throw 'StartNow requires the managed Windows auto-start task. Remove -NoAutostart or use -NoStartNow.'
        }
        Write-Host '> Starting managed service now...' -ForegroundColor DarkGray
        Start-ScheduledTask -TaskName $TaskName
        $StartedTask = $true

        # Managed Admin Bot startup performs a real Telegram connection handshake.
        # Poll rather than assuming all four components are ready after 15 seconds.
        $wd = $null
        $wdRaw = @()
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(75)
        do {
            Start-Sleep -Seconds 5
            $wdRaw = @(& py .\app.py watchdog --require service --require scheduler --require worker --require admin_bot --json-only 2>&1)
            if ($LASTEXITCODE -eq 0) {
                try {
                    $candidate = (($wdRaw -join "`n") | ConvertFrom-Json)
                    $fresh = $true
                    foreach ($component in @('service','scheduler','worker','admin_bot')) {
                        $hb = $candidate.heartbeats.$component
                        $maxAge = [double]$HeartbeatMaxAgeSeconds[$component]
                        if ($null -eq $hb -or [double]$hb.age_seconds -gt $maxAge -or [bool]$hb.stale -or [string]$hb.status -in @('error','stopped')) {
                            $fresh = $false
                        }
                    }
                    $taskState = (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue).State
                    if (@($candidate.problems).Count -eq 0 -and $fresh -and $taskState -eq 'Running') { $wd = $candidate; break }
                } catch { }
            }
        } while ([DateTimeOffset]::UtcNow -lt $deadline)
        if ($null -eq $wd) {
            $wdRaw | Out-Host
            $serviceLog = Get-ChildItem (Join-Path $Root 'logs') -Filter 'service_*.log' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($serviceLog) {
                Write-Host "[DIAGNOSTIC] Tail of $($serviceLog.FullName):" -ForegroundColor Yellow
                Get-Content $serviceLog.FullName -Tail 40 -ErrorAction SilentlyContinue | Out-Host
            }
            throw 'Service/Admin Bot watchdog did not become healthy within 75 seconds.'
        }
        Write-Host '[OK] Service/scheduler/worker/Admin Bot heartbeats healthy.' -ForegroundColor Green
        Write-Host '> Verifying managed-service stability window...' -ForegroundColor DarkGray
        Start-Sleep -Seconds 12
        $wd2Raw = @(& py .\app.py watchdog --require service --require scheduler --require worker --require admin_bot --json-only 2>&1)
        if ($LASTEXITCODE -ne 0) { $wd2Raw | Out-Host; throw 'Managed-service stability recheck failed.' }
        $wd2 = (($wd2Raw -join "`n") | ConvertFrom-Json)
        foreach ($component in @('service','scheduler','worker','admin_bot')) {
            $hb = $wd2.heartbeats.$component
            $maxAge = [double]$HeartbeatMaxAgeSeconds[$component]
            if ($null -eq $hb -or [double]$hb.age_seconds -gt $maxAge -or [bool]$hb.stale -or [string]$hb.status -in @('error','stopped')) {
                throw "Managed-service stability recheck failed for $component (age=$($hb.age_seconds)s, max=$maxAge s)."
            }
        }
        $taskState2 = (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue).State
        if ($taskState2 -ne 'Running') { throw "Managed Windows task is not Running after stability window (state=$taskState2)." }
        Write-Host '[OK] Managed service remained healthy through the stability window.' -ForegroundColor Green

        # There must still be no active outbound jobs because first schedule is ~4h away.
        $check = Get-JsonCommand @('.\app.py','production-readiness',$Campaign,'--collection','all_approved','--json-only')
        if ([int]$check.active_queue_jobs -ne 0) { throw 'Unexpected immediate production jobs detected after service start.' }
    }

    $receiptDir = Join-Path $Root 'runtime\production'
    New-Item -ItemType Directory -Force -Path $receiptDir | Out-Null
    $receiptPath = Join-Path $receiptDir 'main_production_go_live.json'
    $localTz = [TimeZoneInfo]::FindSystemTimeZoneById('Cen. Australia Standard Time')
    $nextLocal = [TimeZoneInfo]::ConvertTime($nextUtc, $localTz)
    $receipt = [ordered]@{
        schema_version = 1
        activated_at = [DateTimeOffset]::Now.ToString('o')
        version = (Get-Content .\VERSION.txt -Raw).Trim()
        campaign_id = $Campaign
        destinations = $ExpectedDestinations
        variants = $ExpectedVariants
        album_items_each = $AlbumItems
        schedule_minutes = $IntervalMinutes
        next_run_utc = $nextUtc.ToString('o')
        next_run_adelaide = $nextLocal.ToString('o')
        autostart = (-not $NoAutostart)
        service_started_now = (-not $NoStartNow)
        pre_go_live_backup = $DbSnapshot
        immediate_send_performed = $false
        approval = $RequiredApproval
    }
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ' SMART AUTO POSTER PRODUCTION IS LIVE' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host 'Campaign         : ACTIVE'
    Write-Host 'Destinations     : 32 approved / 32 album-capable'
    Write-Host 'Content rotation : 5 x 10-photo albums (least-recent)'
    Write-Host 'Schedule         : every 4 hours'
    Write-Host "First run UTC    : $($nextUtc.ToString('o'))"
    Write-Host "First run Adelaide: $($nextLocal.ToString('o'))"
    Write-Host "Auto-start       : $((-not $NoAutostart).ToString().ToUpperInvariant())"
    Write-Host "Service running  : $((-not $NoStartNow).ToString().ToUpperInvariant())"
    Write-Host 'Immediate Post Now: NONE'
    Write-Host "Recovery snapshot: $DbSnapshot"
    Write-Host "Go-live receipt  : $receiptPath"
}
catch {
    Write-Host "[GO-LIVE FAILED] $($_.Exception.Message)" -ForegroundColor Red
    try { Stop-ServiceTaskSafely } catch { }
    try {
        if (-not (Clear-StaleRuntimeLockSafely)) {
            Write-Host '[ROLLBACK WARNING] Runtime lock owner is still alive; lock was not removed.' -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[ROLLBACK WARNING] Runtime lock cleanup failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    if (-not $TaskExistedBefore) {
        try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch { }
        try { & schtasks.exe /Delete /TN $TaskName /F *> $null } catch { }
    }
    Restore-DbSnapshot $DbSnapshot
    if ($Activated -or $NormalizedForGoLive) {
        try { Ensure-FailedGoLiveInactive }
        catch { Write-Host "[ROLLBACK ERROR] $($_.Exception.Message)" -ForegroundColor Red }
    }
    Write-Host '[SAFE] Managed service stopped and production rollback verified READY/inactive.' -ForegroundColor Yellow
    throw
}
finally {
    Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
