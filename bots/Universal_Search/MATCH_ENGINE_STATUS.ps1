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
    $payload | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host '============================================================'
Write-Host ' UNIVERSAL SEARCH - MATCH ENGINE STATUS'
Write-Host '============================================================'
Write-Host ("Scheduled task : {0}" -f $taskState)

if ($daemon) {
    Write-Host ("Daemon state   : {0}" -f $daemon.state)
    Write-Host ("Updated UTC    : {0}" -f $daemon.updated_utc)
    Write-Host ("PID            : {0}" -f $daemon.pid)
    Write-Host ("Notifications  : {0}" -f $daemon.notifications_enabled)
    Write-Host ("Matches active : {0}" -f $daemon.matches_active)
    Write-Host ("Matches new    : {0}" -f $daemon.matches_new)
    Write-Host ("High confidence: {0}" -f $daemon.matches_high_confidence)
    if ($daemon.alert_queue) {
        $queueParts = @()
        $daemon.alert_queue.psobject.Properties | Sort-Object Name | ForEach-Object {
            $queueParts += ("{0}={1}" -f $_.Name, $_.Value)
        }
        Write-Host ("Alert queue    : {0}" -f ($queueParts -join ' '))
    }
    if ($daemon.error_type) {
        Write-Host ("Last error     : {0}: {1}" -f $daemon.error_type, $daemon.error)
    }
}
else {
    Write-Host 'Daemon state   : no status file yet'
}

Write-Host ''
& py .\match_cli.py stats
if ($LASTEXITCODE -ne 0) {
    throw "match_cli.py stats failed with exit code $LASTEXITCODE"
}
