param([switch]$Refresh,[int]$WaitSeconds=0)
$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$env:PYTHONPATH="$Root;$env:PYTHONPATH"
if($Refresh){
 py -m shared.vm_intelligence.cli --root "$Root" cycle
 if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
}
$PidFile=Join-Path $Root "state\vm_intelligence_agent.pid"
$deadline=(Get-Date).AddSeconds([Math]::Max(0,$WaitSeconds))
do{
 $alive=$false;$pidValue=$null
 if(Test-Path $PidFile){
  try{
   $pidValue=[int](Get-Content $PidFile -Raw).Trim()
   $alive=[bool](Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
  }catch{}
 }
 if($alive -or (Get-Date) -ge $deadline){break}
 Start-Sleep -Milliseconds 500
}while($true)

Write-Host "VM Intelligence agent: $(if($alive){'RUNNING'}else{'NOT CONFIRMED'})$(if($pidValue){' PID '+$pidValue}else{''})"
$Brief=Join-Path $Root "diagnostics\intelligence_brief.txt"
if(Test-Path $Brief){
 Write-Host ""
 Get-Content $Brief
}else{
 Write-Host "No intelligence brief exists yet. Use -Refresh to generate one."
}
if(-not $alive){exit 2}
exit 0
