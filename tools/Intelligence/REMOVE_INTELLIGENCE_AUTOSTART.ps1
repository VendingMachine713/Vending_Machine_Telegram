$Startup=[Environment]::GetFolderPath("Startup")
$Vbs=Join-Path $Startup "VMIntelligenceAgent.vbs"
Remove-Item -LiteralPath $Vbs -Force -ErrorAction SilentlyContinue
Write-Host "[OK] Intelligence autostart registration removed." -ForegroundColor Green
