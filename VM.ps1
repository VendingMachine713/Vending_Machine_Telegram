param([Parameter(Position=0)][string]$Command="help")
$Controller = Join-Path $PSScriptRoot "tools\vm_core\VM.ps1"
if (!(Test-Path $Controller)) { Write-Host "[FAIL] Missing $Controller"; exit 1 }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Controller $Command
exit $LASTEXITCODE
