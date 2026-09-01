$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
Write-Host ""
Write-Host "============================================================"
Write-Host " VM ECOSYSTEM v1.2.0 - PLATFORM + ADMIN CONTROL PLANE"
Write-Host "============================================================"
Write-Host ""
if (-not (Test-Path ".\bots" -PathType Container)) { Write-Host "[ERROR] Expected .\bots beside this installer."; exit 1 }
Write-Host "[1/7] Initialising VM Platform..."; py .\vm.py init; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[2/7] Refreshing manifests and inventory..."; py .\vm.py manifests --refresh --write; py .\vm.py inventory
Write-Host "[3/7] Checking nested duplicate folders..."; py .\vm.py duplicates
Write-Host "[4/7] Running platform tests..."; py .\vm.py test; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[5/7] Running Admin Command Centre self-test..."; py .\bots\Admin_Command_Centre\main.py --self-test; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[6/7] Running VM Doctor..."; py .\vm.py doctor; $DoctorExit = $LASTEXITCODE
Write-Host "[7/7] Dashboard..."; py .\vm.py dashboard
Write-Host ""
Write-Host "============================================================"
Write-Host " VM ECOSYSTEM v1.2.0 INSTALLED"
Write-Host "============================================================"
Write-Host "Admin Command Centre will show CONFIG_REQUIRED until its local .env is configured."
Write-Host "Start read-only with VM_ADMIN_ALLOW_MUTATIONS=false."
