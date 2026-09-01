$ErrorActionPreference = 'Stop'
$TaskName = 'VendingMachine Smart Auto Poster V2'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Not installed: $TaskName" -ForegroundColor Yellow
    exit 1
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Task: $TaskName"
Write-Host "State: $($task.State)"
Write-Host "Last run: $($info.LastRunTime)"
Write-Host "Last result: $($info.LastTaskResult)"
Write-Host "Next run: $($info.NextRunTime)"
Write-Host "Triggers: $(@($task.Triggers).Count)"
$i = 0
foreach ($trigger in @($task.Triggers)) {
    $i++
    $start = if ($trigger.StartBoundary) { $trigger.StartBoundary } else { '-' }
    $interval = if ($trigger.Repetition -and $trigger.Repetition.Interval) { $trigger.Repetition.Interval } else { '-' }
    Write-Host "  [$i] start=$start repetition=$interval"
}
Write-Host "Multiple instances: $($task.Settings.MultipleInstances)"
