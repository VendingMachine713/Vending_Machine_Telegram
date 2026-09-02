$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = 'VendingMachine Smart Auto Poster V2'
$RunScript = Join-Path $Root 'RUN_SERVICE.ps1'
if (-not (Test-Path $RunScript)) { throw "Missing $RunScript" }
$PowerShell = (Get-Command powershell.exe).Source
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`""
try {
    $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $Root
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    try { $Trigger.Delay = 'PT20S' } catch {}
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Starts Smart Auto Poster V2.4 at Windows logon after a short delay.' -Force | Out-Null
    Write-Host "[OK] Windows auto-start installed: $TaskName" -ForegroundColor Green
    Write-Host 'It will start on your next Windows logon. This installer did NOT start outbound posting now.' -ForegroundColor Yellow
} catch {
    Write-Host "[ERROR] Could not install scheduled task: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Try opening PowerShell as Administrator and running this script again.' -ForegroundColor Yellow
    exit 2
}
