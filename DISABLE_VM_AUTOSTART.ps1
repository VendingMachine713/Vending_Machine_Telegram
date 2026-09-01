$ErrorActionPreference = "SilentlyContinue"
Unregister-ScheduledTask -TaskName "VendingMachineTelegram" -Confirm:$false | Out-Null
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\VendingMachineTelegram.vbs"
Remove-Item -LiteralPath $startup -Force -ErrorAction SilentlyContinue
Write-Host "[OK] VM autostart disabled (Task Scheduler + Startup fallback cleared)."
