$ErrorActionPreference="SilentlyContinue"
$me=$PID
$rows=Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $me -and
    $_.Name -match 'python|py' -and
    $_.CommandLine -match 'shared\.vm_intelligence\.cli' -and
    $_.CommandLine -match '\bagent\b'
}
foreach($row in $rows){
    Stop-Process -Id $row.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Stopped previous VM Intelligence agent PID $($row.ProcessId)"
}
Start-Sleep -Seconds 1
