$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Startup=[Environment]::GetFolderPath("Startup")
$Vbs=Join-Path $Startup "VMIntelligenceAgent.vbs"
$Ps=Join-Path $Root "tools\Intelligence\RUN_INTELLIGENCE_AGENT.ps1"
$escaped=$Ps.Replace('"','""')
$content=@"
Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$escaped""", 0, False
"@
Set-Content -LiteralPath $Vbs -Value $content -Encoding ASCII
Write-Host "[OK] Intelligence autostart registered: $Vbs" -ForegroundColor Green
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$Ps)
Write-Host "[OK] Intelligence agent launch requested." -ForegroundColor Green
