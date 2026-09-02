param(
    [switch]$StopRunning
)

$ErrorActionPreference = 'Stop'
$TaskName = 'VendingMachine Universal Search Match Engine'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "[OK] Match Engine auto-start is not installed. Nothing to remove."
    exit 0
}

if ($StopRunning) {
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Write-Host "[OK] Stop requested for scheduled Match Engine instance."
    }
    catch {
        Write-Host "[INFO] Scheduled task was not running or could not be stopped: $($_.Exception.Message)"
    }
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Windows auto-start removed: $TaskName"
Write-Host "[INFO] Match database, feedback, queue history and configuration were preserved."
