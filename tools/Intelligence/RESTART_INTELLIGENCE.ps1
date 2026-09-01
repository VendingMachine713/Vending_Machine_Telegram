$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
& (Join-Path $Root "tools\Intelligence\STOP_INTELLIGENCE_AGENT.ps1")
Start-Sleep -Seconds 1
$Ps=Join-Path $Root "tools\Intelligence\RUN_INTELLIGENCE_AGENT.ps1"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$Ps)
Start-Sleep -Seconds 3
& (Join-Path $Root "tools\Intelligence\INTELLIGENCE_STATUS.ps1")
exit $LASTEXITCODE
