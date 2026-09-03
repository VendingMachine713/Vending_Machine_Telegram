$ErrorActionPreference = "Continue"
$taskName = "VM_Relationship_Manager"
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "[+] VM Relationship Manager autostart task removed."
