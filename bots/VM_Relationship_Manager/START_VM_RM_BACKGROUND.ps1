$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$taskName = "VM_Relationship_Manager"
$stopFile = Join-Path $PSScriptRoot "runtime\watchdog.stop"
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Autostart task is not installed. Run INSTALL_VM_RM_AUTOSTART.ps1 first."
}
Start-ScheduledTask -TaskName $taskName
Write-Host "[+] VM Relationship Manager background watchdog started."
