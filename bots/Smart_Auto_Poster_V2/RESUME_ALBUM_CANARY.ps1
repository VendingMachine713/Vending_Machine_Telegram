param(
    [ValidateSet('AUTO','NOW')]
    [string]$Mode = 'AUTO',
    [ValidateRange(30,900)]
    [int]$SettleTimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$TaskName = 'VM Smart Auto Poster Album Canary Retry'
$ScriptPath = $MyInvocation.MyCommand.Path
$ReceiptDir = Join-Path $Root 'runtime\canary'
$ReceiptPath = Join-Path $ReceiptDir 'album_canary_last_result.json'
$RuntimeOwnerPath = Join-Path $Root 'runtime\telegram_runtime.lock\owner.json'
New-Item -ItemType Directory -Path $ReceiptDir -Force | Out-Null

function Get-CanaryStatus {
    $raw = & py .\app.py canary-status --campaign-id album_canary_01 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read album canary status: $($raw -join [Environment]::NewLine)"
    }
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Remove-RetryTask {
    try {
        & schtasks.exe /Delete /TN $TaskName /F *> $null
    } catch { }
}

function Get-ManagedRuntimeOwner {
    if (-not (Test-Path -LiteralPath $RuntimeOwnerPath)) { return $null }
    try {
        $owner = Get-Content -LiteralPath $RuntimeOwnerPath -Raw | ConvertFrom-Json
        $pidValue = [int]$owner.pid
        if ($pidValue -le 0) { return $null }
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if (-not $process) { return $null }
        return [pscustomobject]@{ Pid=$pidValue; Process=$process }
    } catch {
        return $null
    }
}

function Wait-ManagedCanary {
    $deadline = (Get-Date).AddSeconds($SettleTimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $last = Get-CanaryStatus
        if ($last.status -notin @('pending','retry','processing','sending')) {
            return $last
        }
    }
    if ($last) { return $last }
    return Get-CanaryStatus
}

function Save-Receipt([object]$Status, [string]$Outcome) {
    $receipt = [ordered]@{
        recorded_at = [DateTimeOffset]::Now.ToString('o')
        outcome = $Outcome
        campaign_id = 'album_canary_01'
        job_id = $Status.id
        status = $Status.status
        group_id = $Status.group_id
        group_name = $Status.group_name
        content_id = $Status.content_id
        attempts = $Status.attempts
        error_kind = $Status.error_kind
        last_error = $Status.last_error
        telegram_message_ids = $Status.telegram_message_ids
        due_at = $Status.due_at
    }
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
}

function Schedule-Retry([DateTimeOffset]$DueUtc) {
    $when = $DueUtc.ToLocalTime().AddSeconds(20)
    if ($when -lt [DateTimeOffset]::Now.AddMinutes(1)) {
        $when = [DateTimeOffset]::Now.AddMinutes(1)
    }
    $powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" AUTO"
    try {
        $action = New-ScheduledTaskAction -Execute $powerShell -Argument $args -WorkingDirectory $Root
        $trigger = New-ScheduledTaskTrigger -Once -At $when.LocalDateTime
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::FromMinutes(20)) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Retries the already-approved Smart Auto Poster album canary queue job once.' -Force | Out-Null
    } catch {
        # Locale-safe fallback: schtasks accepts an ISO-derived local time but date parsing can vary,
        # so use the ScheduledTasks module whenever available and only fall back if necessary.
        $date = $when.ToString('MM/dd/yyyy',[Globalization.CultureInfo]::InvariantCulture)
        $time = $when.ToString('HH:mm',[Globalization.CultureInfo]::InvariantCulture)
        $taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" AUTO"
        & schtasks.exe /Create /TN $TaskName /SC ONCE /SD $date /ST $time /TR $taskCommand /F | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create one-time retry task. Existing canary queue job remains safe and unsent."
        }
    }
    Write-Host "[SCHEDULED] Existing canary job will be retried at $($when.ToString('yyyy-MM-dd HH:mm:ss zzz'))." -ForegroundColor Green
    Write-Host '[SAFE] No new queue job was created.' -ForegroundColor Green
}

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - RESUME EXISTING ALBUM CANARY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This script NEVER creates a new canary queue job.' -ForegroundColor Yellow
Write-Host 'It only resumes the already-approved existing job after Telegram timing restrictions.' -ForegroundColor Yellow
Write-Host ''

$status = Get-CanaryStatus
$status | ConvertTo-Json -Depth 6 | Out-Host

if ($status.status -eq 'sent') {
    Remove-RetryTask
    Save-Receipt $status 'sent'
    & py .\app.py campaign-state album_canary_01 paused | Out-Host
    Write-Host '[OK] Album canary is already SENT. No further Telegram action performed.' -ForegroundColor Green
    exit 0
}

if ($status.status -notin @('pending','retry','deferred')) {
    Remove-RetryTask
    Save-Receipt $status 'blocked'
    throw "Canary is in terminal/non-resumable state '$($status.status)'. Automatic retry blocked."
}

$dueUtc = [DateTimeOffset]::Parse([string]$status.due_at).ToUniversalTime()
if ($Mode -eq 'AUTO' -and $dueUtc -gt [DateTimeOffset]::UtcNow.AddSeconds(5)) {
    Schedule-Retry $dueUtc
    Save-Receipt $status 'scheduled'
    exit 0
}

# Resume ONLY the existing queue job. Do not call post-now/enqueue.
$activated = $false
$managedOwner = Get-ManagedRuntimeOwner
try {
    & py .\app.py production-readiness album_canary_01 --collection live_test | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Album canary readiness failed. Existing queue job was not processed.' }

    & py .\app.py campaign-state album_canary_01 active | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not activate album canary for retry.' }
    $activated = $true

    if ($managedOwner) {
        Write-Host "[MANAGED] Existing Telegram runtime PID $($managedOwner.Pid) will process job #$($status.id)." -ForegroundColor Cyan
        Write-Host '[SAFE] No competing worker will be started.' -ForegroundColor Green
        $managedResult = Wait-ManagedCanary
        if ($managedResult.status -in @('pending','retry','processing','sending')) {
            throw "Managed canary did not settle within $SettleTimeoutSeconds seconds (status=$($managedResult.status))."
        }
    } else {
        & py .\app.py worker --once | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Canary retry worker failed.' }
    }
}
finally {
    if ($activated) {
        & py .\app.py campaign-state album_canary_01 paused | Out-Host
    }
}

$after = Get-CanaryStatus
Write-Host ''
Write-Host '> Canary result after existing-job retry...' -ForegroundColor DarkGray
$after | ConvertTo-Json -Depth 6 | Out-Host
Save-Receipt $after $after.status

if ($after.status -eq 'sent') {
    Remove-RetryTask
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ' ALBUM CANARY SENT - CAMPAIGN PAUSED AGAIN' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host "Receipt: $ReceiptPath"
    exit 0
}

if ($after.status -in @('retry','deferred','pending')) {
    $nextDue = [DateTimeOffset]::Parse([string]$after.due_at).ToUniversalTime()
    Schedule-Retry $nextDue
    Write-Host '[INFO] Telegram requested another timing deferral; the SAME queue job remains scheduled.' -ForegroundColor Yellow
    exit 0
}

Remove-RetryTask
throw "Canary retry ended in '$($after.status)'. Production remains inactive."
