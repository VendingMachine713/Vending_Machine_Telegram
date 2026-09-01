$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "VendingMachineTelegram"
$runner = Join-Path $root "START_VM_MANAGED.bat"

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Managed-service runner not found: $runner"
}

$registered = $false
$method = $null
try {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Start managed Vending Machine Telegram services at user logon." -Force | Out-Null
    $registered = $true
    $method = "Task Scheduler"
} catch {
    Write-Host "[WARN] Task Scheduler registration was unavailable. Using per-user Startup fallback." -ForegroundColor Yellow
}

if (-not $registered) {
    $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    New-Item -ItemType Directory -Force -Path $startup | Out-Null
    $vbs = Join-Path $startup "VendingMachineTelegram.vbs"
    $escapedRunner = $runner.Replace('"','""')
    $content = @"
Set shell = CreateObject("WScript.Shell")
shell.Run Chr(34) & "$escapedRunner" & Chr(34), 0, False
"@
    Set-Content -LiteralPath $vbs -Value $content -Encoding ASCII
    if (-not (Test-Path -LiteralPath $vbs -PathType Leaf)) {
        throw "Startup fallback could not be created."
    }
    $registered = $true
    $method = "Startup folder"
}

Write-Host "[OK] VM autostart enabled via $method." -ForegroundColor Green
