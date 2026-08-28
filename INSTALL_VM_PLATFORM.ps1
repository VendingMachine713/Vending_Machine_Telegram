$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host ""
Write-Host "============================================================"
Write-Host " VM PLATFORM FOUNDATION v0.2.0"
Write-Host "============================================================"
Write-Host ""

if (-not (Test-Path ".\bots" -PathType Container)) {
    Write-Host "[!] This update must be extracted into the Vending_Machine_Telegram root."
    exit 1
}

Write-Host "[1/5] Initialising platform..."
py .\vm.py init
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/5] Refreshing inventory..."
py .\vm.py inventory
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] Inspecting bot structure safely..."
py .\vm.py inspect
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/5] Running platform self-tests..."
py .\vm.py test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/5] Running VM Doctor..."
py .\vm.py doctor
$DoctorExit = $LASTEXITCODE

Write-Host ""
Write-Host "VM Platform v0.2.0 installed."
Write-Host "No existing bot files, databases, configs, sessions or manifests were replaced."
Write-Host ""
Write-Host "Structure report:"
Write-Host "  diagnostics\project_structure.txt"
Write-Host ""

if ($DoctorExit -eq 2) { exit 2 }
