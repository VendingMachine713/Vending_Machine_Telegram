param(
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$TaskName = 'VendingMachine Universal Search Match Engine'
$Runner = Join-Path $PSScriptRoot 'RUN_MATCH_ENGINE.ps1'

if (-not (Test-Path $Runner)) {
    throw "Runner not found: $Runner"
}

$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $PSScriptRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

Write-Host "[OK] Windows auto-start installed/refreshed: $TaskName"
Write-Host "[SAFE] The daemon only sends private match alerts; it does not poll Telegram updates."

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Match Engine start requested through Task Scheduler."
}
