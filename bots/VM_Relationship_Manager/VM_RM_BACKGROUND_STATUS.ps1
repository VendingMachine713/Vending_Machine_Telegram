$taskName = "VM_Relationship_Manager"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task installed: No"
    exit 0
}
$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
Write-Host "Task installed: Yes"
Write-Host "Task state:" $task.State
if ($info) {
    Write-Host "Last run:" $info.LastRunTime
    Write-Host "Last result:" $info.LastTaskResult
    Write-Host "Next run:" $info.NextRunTime
}
$stopFile = Join-Path $PSScriptRoot "runtime\watchdog.stop"
Write-Host "Watchdog stop sentinel:" (Test-Path -LiteralPath $stopFile)
