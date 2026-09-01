$ErrorActionPreference = 'Stop'
$BotRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MasterRoot = (Resolve-Path (Join-Path $BotRoot '..\..')).Path
$Source = Join-Path $BotRoot 'master_updater'
if (-not (Test-Path $Source)) { throw "Missing master_updater folder: $Source" }
@('inbox','applied','failed','backups') | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $MasterRoot "updates\$_") | Out-Null }
Copy-Item (Join-Path $Source 'APPLY_UPDATE.ps1') (Join-Path $MasterRoot 'APPLY_UPDATE.ps1') -Force
Copy-Item (Join-Path $Source 'ROLLBACK_LAST_UPDATE.ps1') (Join-Path $MasterRoot 'ROLLBACK_LAST_UPDATE.ps1') -Force
Write-Host "[OK] Master update system installed at: $MasterRoot" -ForegroundColor Green
Write-Host 'Future update: drop the bot update ZIP into updates\inbox and run APPLY_UPDATE.ps1.' -ForegroundColor Cyan
