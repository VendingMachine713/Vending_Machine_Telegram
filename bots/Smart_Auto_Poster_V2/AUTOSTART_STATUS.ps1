$TaskName = 'VendingMachine Smart Auto Poster V2'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Host '[OFF] Windows auto-start is not installed.' -ForegroundColor Yellow; exit 0 }
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "[ON] $TaskName" -ForegroundColor Green
Write-Host "State: $($task.State)"
Write-Host "Last run: $($info.LastRunTime)"
Write-Host "Last result: $($info.LastTaskResult)"
Write-Host "Next run: $($info.NextRunTime)"
