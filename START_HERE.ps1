$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Open-Project($RelativePath, $Launcher = $null) {
    $Path = Join-Path $Root $RelativePath
    if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
    Start-Process explorer.exe $Path
    $cmd = "Set-Location -LiteralPath '$Path'"
    if ($Launcher) { $cmd += "; if (Test-Path '.\$Launcher') { & '.\$Launcher' }" }
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd
}

function Open-MissionControl {
    $cmd = "Set-Location -LiteralPath '$Root'; py '.\tools\vm_brain_phase2.py' home"
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd
}

function Open-OperatorGuide {
    $Guide = Join-Path $Root "docs\OPERATOR_GUIDE.md"
    if (Test-Path $Guide) {
        Start-Process $Guide
    } else {
        Write-Host "Operator guide not found: $Guide" -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    }
}

while ($true) {
    Clear-Host
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " VENDING MACHINE TELEGRAM - PROJECT LAUNCHER" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "M. Mission Control - operator home" -ForegroundColor Green
    Write-Host "G. Operator Guide - what everything does" -ForegroundColor Green
    Write-Host ""
    Write-Host "1. Smart Auto Poster V2"
    Write-Host "2. VM Guard"
    Write-Host "3. Universal Search"
    Write-Host "4. Admin Command Centre"
    Write-Host "5. VM Relationship Manager"
    Write-Host "6. Group Scanner tools"
    Write-Host "7. Maintenance tools"
    Write-Host "8. Shared files"
    Write-Host "9. Open master folder"
    Write-Host "0. Exit"
    Write-Host ""

    switch ((Read-Host "Select an option").ToUpperInvariant()) {
        "M" { Open-MissionControl }
        "G" { Open-OperatorGuide }
        "1" { Open-Project "bots\Smart_Auto_Poster_V2" }
        "2" { Open-Project "bots\VM_Guard" }
        "3" { Open-Project "bots\Universal_Search" }
        "4" { Open-Project "bots\Admin_Command_Centre" }
        "5" { Open-Project "bots\VM_Relationship_Manager" "START_VM_RELATIONSHIPS.ps1" }
        "6" { Open-Project "tools\Group_Scanner" }
        "7" { Open-Project "tools\Maintenance" }
        "8" { Start-Process explorer.exe (Join-Path $Root "shared") }
        "9" { Start-Process explorer.exe $Root }
        "0" { break }
        default { Start-Sleep -Seconds 1 }
    }
    if ($LASTEXITCODE -eq 0 -and $?) { }
}
