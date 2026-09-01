$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$taskName = "VM_Relationship_Manager"
$runtime = Join-Path $PSScriptRoot "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$stopFile = Join-Path $runtime "watchdog.stop"
Set-Content -LiteralPath $stopFile -Value "stopped $(Get-Date -Format o)" -Encoding ASCII
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Write-Host "[+] Background watchdog stop requested."
Write-Host "[+] Autostart task remains installed but watchdog will stay stopped until START_VM_RM_BACKGROUND.ps1 or reinstall removes the stop sentinel."
