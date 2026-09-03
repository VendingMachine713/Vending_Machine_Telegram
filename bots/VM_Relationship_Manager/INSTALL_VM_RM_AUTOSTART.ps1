$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$taskName = "VM_Relationship_Manager"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$watchdog = Join-Path $PSScriptRoot "RUN_VM_RM_WATCHDOG.ps1"
$stopFile = Join-Path $PSScriptRoot "runtime\watchdog.stop"

if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "Missing watchdog script: $watchdog"
}

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "runtime") | Out-Null
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdog`"" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 12 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Host "[+] VM Relationship Manager background autostart installed."
Write-Host "[+] Task:" $taskName
Write-Host "[+] User:" $user
Write-Host "[+] It will start at logon and the watchdog will restart the bot after process exits."
Write-Host "[+] Single-instance locking prevents a background and manual instance from polling Telegram simultaneously."
