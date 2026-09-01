param(
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = 'VendingMachine Smart Auto Poster V2'
$RecoveryIntervalMinutes = 5
$RunScript = Join-Path $Root 'RUN_SERVICE.ps1'
if (-not (Test-Path $RunScript)) { throw "Missing $RunScript" }
$PowerShell = (Get-Command powershell.exe).Source
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`""
$registered = $false

try {
    $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $Root
    $LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    try { $LogonTrigger.Delay = 'PT20S' } catch {}
    # A second trigger acts as a liveness safety net. MultipleInstances=IgnoreNew
    # means it does nothing while the managed runtime is healthy, but if the
    # PowerShell/Python host is externally terminated the next interval restarts it.
    $RecoveryTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes($RecoveryIntervalMinutes)) -RepetitionInterval (New-TimeSpan -Minutes $RecoveryIntervalMinutes)
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($LogonTrigger,$RecoveryTrigger) -Settings $Settings -Description "Starts Smart Auto Poster at logon and self-recovers every $RecoveryIntervalMinutes minutes if the managed runtime is not running." -Force | Out-Null
    $registered = $true
} catch {
    Write-Host "[WARNING] Register-ScheduledTask failed: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host '[FALLBACK] Trying current-user schtasks registration...' -ForegroundColor Yellow
    try {
        $tr = "`"$PowerShell`" $Arguments"
        # Fallback favours liveness over logon-only behaviour. RuntimeLock and the
        # normal task policy prevent duplicate Smart Auto Poster runtimes.
        & schtasks.exe /Create /TN $TaskName /TR $tr /SC MINUTE /MO $RecoveryIntervalMinutes /F /RL LIMITED | Out-Host
        if ($LASTEXITCODE -eq 0) { $registered = $true }
    } catch { }
}

if (-not $registered) {
    Write-Host '[ERROR] Could not install Windows auto-start task.' -ForegroundColor Red
    Write-Host 'Try opening PowerShell as Administrator and running this script again.' -ForegroundColor Yellow
    exit 2
}

Write-Host "[OK] Windows auto-start/self-heal installed/refreshed: $TaskName" -ForegroundColor Green
if ($StartNow) {
    try {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        & schtasks.exe /Run /TN $TaskName | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Could not start scheduled task: $TaskName" }
    }
    Write-Host '[OK] Service start requested now through Windows Task Scheduler.' -ForegroundColor Green
} else {
    Write-Host "It will start at the next logon or the next $RecoveryIntervalMinutes-minute recovery trigger. This installer did NOT start outbound posting now." -ForegroundColor Yellow
}
