$TaskName = 'VendingMachine Smart Auto Poster V2'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "[OK] Auto-start task is not installed." -ForegroundColor Green
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Windows auto-start removed: $TaskName" -ForegroundColor Green
