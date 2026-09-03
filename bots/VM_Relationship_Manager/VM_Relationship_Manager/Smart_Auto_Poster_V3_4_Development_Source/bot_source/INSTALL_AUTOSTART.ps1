param(
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = 'VendingMachine Smart Auto Poster V2'
$RunScript = Join-Path $Root 'RUN_SERVICE.ps1'
if (-not (Test-Path $RunScript)) { throw "Missing $RunScript" }
$PowerShell = (Get-Command powershell.exe).Source
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`""
$registered = $false

try {
    $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $Root
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    try { $Trigger.Delay = 'PT20S' } catch {}
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Starts Smart Auto Poster at Windows logon after a short delay.' -Force | Out-Null
    $registered = $true
} catch {
    Write-Host "[WARNING] Register-ScheduledTask failed: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host '[FALLBACK] Trying current-user schtasks registration...' -ForegroundColor Yellow
    try {
        $tr = "`"$PowerShell`" $Arguments"
        & schtasks.exe /Create /TN $TaskName /TR $tr /SC ONLOGON /F /RL LIMITED | Out-Host
        if ($LASTEXITCODE -eq 0) { $registered = $true }
    } catch { }
}

if (-not $registered) {
    Write-Host '[ERROR] Could not install Windows auto-start task.' -ForegroundColor Red
    Write-Host 'Try opening PowerShell as Administrator and running this script again.' -ForegroundColor Yellow
    exit 2
}

Write-Host "[OK] Windows auto-start installed/refreshed: $TaskName" -ForegroundColor Green
if ($StartNow) {
    try {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        & schtasks.exe /Run /TN $TaskName | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Could not start scheduled task: $TaskName" }
    }
    Write-Host '[OK] Service start requested now through Windows Task Scheduler.' -ForegroundColor Green
} else {
    Write-Host 'It will start on your next Windows logon. This installer did NOT start outbound posting now.' -ForegroundColor Yellow
}
