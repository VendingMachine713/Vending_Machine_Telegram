param(
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$TaskName = 'VendingMachine Universal Search Match Engine'
$StatusFile = Join-Path $PSScriptRoot 'state\match_engine_status.json'

$taskState = 'not-installed'
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskState = [string]$task.State
}
catch {
    $task = $null
}

$daemon = $null
if (Test-Path $StatusFile) {
    try {
        $daemon = Get-Content $StatusFile -Raw | ConvertFrom-Json
    }
    catch {
        $daemon = [pscustomobject]@{
            state = 'status-file-error'
            error = $_.Exception.Message
        }
    }
}

$payload = [ordered]@{
    task_name = $TaskName
    task_state = $taskState
    daemon_status_file = if (Test-Path $StatusFile) { $StatusFile } else { $null }
    daemon = $daemon
}

if ($Json) {
    $payload | ConvertTo-Json -Depth 12
    exit 0
}

Write-Host '============================================================'
Write-Host ' UNIVERSAL SEARCH - MATCH ENGINE STATUS'
Write-Host '============================================================'
Write-Host ("Scheduled task : {0}" -f $taskState)

if ($daemon) {
    Write-Host ("Daemon state   : {0}" -f $daemon.state)
    if ($daemon.engine_mode) {
        Write-Host ("Engine mode    : {0}" -f $daemon.engine_mode)
    }
    Write-Host ("Updated UTC    : {0}" -f $daemon.updated_utc)
    Write-Host ("PID            : {0}" -f $daemon.pid)
    Write-Host ("Notifications  : {0}" -f $daemon.notifications_enabled)
    Write-Host ("Matches active : {0}" -f $daemon.matches_active)
    Write-Host ("Matches new    : {0}" -f $daemon.matches_new)
    Write-Host ("High confidence: {0}" -f $daemon.matches_high_confidence)
    if ($null -ne $daemon.event_backlog) {
        Write-Host ("Event backlog  : {0}" -f $daemon.event_backlog)
    }
    if ($daemon.demand) {
        Write-Host ("Active WTB     : {0}" -f $daemon.demand.active_wtb)
        Write-Host ("Matched WTB    : {0}" -f $daemon.demand.matched_wtb)
        Write-Host ("Unmatched WTB  : {0}" -f $daemon.demand.unmatched_wtb)
        Write-Host ("WTB expiring 7d: {0}" -f $daemon.demand.expiring_within_7d)
    }
    if ($daemon.match_alert_queue) {
        $queueParts = @()
        $daemon.match_alert_queue.psobject.Properties | Sort-Object Name | ForEach-Object {
            $queueParts += ("{0}={1}" -f $_.Name, $_.Value)
        }
        Write-Host ("Match queue    : {0}" -f ($queueParts -join ' '))
    }
    elseif ($daemon.alert_queue) {
        # Backward-compatible display for v1.5 status files.
        $queueParts = @()
        $daemon.alert_queue.psobject.Properties | Sort-Object Name | ForEach-Object {
            $queueParts += ("{0}={1}" -f $_.Name, $_.Value)
        }
        Write-Host ("Match queue    : {0}" -f ($queueParts -join ' '))
    }
    if ($daemon.wtb_reminder_queue) {
        $reminderParts = @()
        $daemon.wtb_reminder_queue.psobject.Properties | Sort-Object Name | ForEach-Object {
            $reminderParts += ("{0}={1}" -f $_.Name, $_.Value)
        }
        Write-Host ("WTB reminders  : {0}" -f ($reminderParts -join ' '))
    }
    if ($daemon.calibration) {
        Write-Host ("Feedback labels: {0}" -f $daemon.calibration.labelled)
        Write-Host ("Advisory score : {0}" -f $daemon.calibration.recommended_threshold)
    }
    if ($daemon.error_type) {
        Write-Host ("Last error     : {0}: {1}" -f $daemon.error_type, $daemon.error)
    }
}
else {
    Write-Host 'Daemon state   : no status file yet'
}

Write-Host ''
Write-Host '> Demand intelligence snapshot'
& py .\match_cli_v2.py demand-stats --alert-score 65
if ($LASTEXITCODE -ne 0) {
    throw "match_cli_v2.py demand-stats failed with exit code $LASTEXITCODE"
}
