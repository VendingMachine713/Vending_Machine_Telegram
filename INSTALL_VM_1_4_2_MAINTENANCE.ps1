$ErrorActionPreference="Stop"
Set-Location -LiteralPath $PSScriptRoot
$PreSnapshot=$env:VM_PRE142_SNAPSHOT
$Downloads=Join-Path $env:USERPROFILE 'Downloads'
$ResultPath=Join-Path $Downloads 'VM_MAINTENANCE_RESULT.txt'
$TranscriptStarted=$false
try {
    Start-Transcript -LiteralPath $ResultPath -Force | Out-Null
    $TranscriptStarted=$true
} catch {}

function Restore-Pre142 {
    param([string]$Snapshot)
    if(-not $Snapshot -or -not (Test-Path -LiteralPath $Snapshot -PathType Container)){ return }
    Write-Host "[ROLLBACK] Restoring pre-v1.4.2 maintenance state..." -ForegroundColor Yellow
    $items=@('shared','tools','tests','VM_CONTROL.bat','CHANGELOG_VM_PLATFORM.md','VM_PROJECT.json','pyproject.toml')
    foreach($i in $items){
        $src=Join-Path $Snapshot $i; $dst=Join-Path $PSScriptRoot $i
        if(Test-Path -LiteralPath $dst){Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $src){
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        }
    }
    $sapSrc=Join-Path $Snapshot 'sap_targets'
    $sapRoot=Join-Path $PSScriptRoot 'bots\Smart_Auto_Poster_V2'
    foreach($rel in @('CONTROL_PANEL.ps1','GO_LIVE.ps1','master_updater\APPLY_UPDATE.ps1','DRIFT_REPAIR_VM_1_4_2.json')){
        $saved=Join-Path $sapSrc $rel; $dest=Join-Path $sapRoot $rel
        $marker=Join-Path $sapSrc ($rel+'.missing')
        if(Test-Path -LiteralPath $marker){
            Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
        } elseif(Test-Path -LiteralPath $saved){
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
            Copy-Item -LiteralPath $saved -Destination $dest -Force
        }
    }
    try { py .\vm.py start-managed --apply | Out-Host } catch {}
}

try {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host " VM PLATFORM v1.4.2 - SELF-DIAGNOSING MAINTENANCE" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan

    Write-Host "[0/10] Stopping managed control services for a clean code reload..." -ForegroundColor Cyan
    foreach($svc in @('Admin_Command_Centre','Universal_Search','VM_Guard')){
        try { py .\vm.py stop $svc --apply | Out-Host } catch {}
    }
    Start-Sleep -Seconds 2

    Write-Host "[1/10] Initialising updated VM Core..." -ForegroundColor Cyan
    py .\vm.py init
    if($LASTEXITCODE -ne 0){throw 'VM Core init failed.'}

    Write-Host "[2/10] Running platform regression suite..." -ForegroundColor Cyan
    py .\vm.py test
    if($LASTEXITCODE -ne 0){throw 'Platform regression suite failed.'}

    Write-Host "[3/10] Previewing Smart Auto Poster drift repair..." -ForegroundColor Cyan
    py .\vm.py sap-repair
    if($LASTEXITCODE -ne 0){throw 'No safe local Smart Auto Poster repair path was found.'}

    Write-Host "[4/10] Applying Smart Auto Poster repair behind its own tests..." -ForegroundColor Cyan
    py .\vm.py sap-repair --apply
    if($LASTEXITCODE -ne 0){throw 'Smart Auto Poster repair failed; its internal rollback was invoked.'}

    Write-Host "[5/10] Running every ecosystem test suite..." -ForegroundColor Cyan
    py .\vm.py test-all
    if($LASTEXITCODE -ne 0){throw 'One or more ecosystem test suites failed.'}

    Write-Host "[6/10] Running full validation + backup..." -ForegroundColor Cyan
    py .\vm.py validate-all
    if($LASTEXITCODE -ne 0){throw 'Full VM validation failed.'}

    Write-Host "[7/10] Refreshing VM Guard alert state..." -ForegroundColor Cyan
    py .\vm.py guard | Out-Host

    Write-Host "[8/10] Relationship Manager cleanup safety preview (NO DELETE)..." -ForegroundColor Cyan
    py .\vm.py relationship-cleanup | Out-Host

    Write-Host "[9/10] Restarting managed services on v1.4.2..." -ForegroundColor Cyan
    py .\vm.py start-managed --apply | Out-Host
    Start-Sleep -Seconds 8
    py .\vm.py runtime-check --require-autostart --require-legacy-components
    if($LASTEXITCODE -ne 0){
        py .\vm.py supervise --apply | Out-Host
        Start-Sleep -Seconds 6
        py .\vm.py runtime-check --require-autostart --require-legacy-components
        if($LASTEXITCODE -ne 0){throw 'Managed runtime verification failed.'}
    }

    Write-Host "[10/10] Creating final support handoff..." -ForegroundColor Cyan
    py .\vm.py runtime | Out-Host
    py .\vm.py git-audit | Out-Host
    py .\vm.py storage | Out-Host
    py .\vm.py support | Out-Host
    py .\vm.py support-text | Out-Host

    $downloads=Join-Path $env:USERPROFILE 'Downloads'
    $latestTxt=Get-ChildItem '.\state\support\VM_SUPPORT_READABLE_*.txt' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($latestTxt){Copy-Item $latestTxt.FullName (Join-Path $downloads 'VM_SUPPORT_READABLE.txt') -Force}
    $latestZip=Get-ChildItem '.\state\support\VM_SUPPORT_*.zip' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($latestZip){Copy-Item $latestZip.FullName (Join-Path $downloads 'VM_SUPPORT_LATEST.zip') -Force}

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host " VM PLATFORM v1.4.2 MAINTENANCE COMPLETE" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "Smart Auto Poster repair: regression-gated"
    Write-Host "Guard alert state: refreshed"
    Write-Host "Relationship duplicate: preview only; NOT deleted"
    Write-Host ("Diagnostics: "+(Join-Path $downloads 'VM_SUPPORT_READABLE.txt'))
    Write-Host ("Maintenance transcript: "+$ResultPath)
    if($TranscriptStarted){ try { Stop-Transcript | Out-Null } catch {} }
    exit 0
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    $FailureMessage=$_.Exception.Message
    try {
        $failureDir=Join-Path $PSScriptRoot 'diagnostics'
        New-Item -ItemType Directory -Force -Path $failureDir | Out-Null
        $failurePath=Join-Path $failureDir 'v142_maintenance_failure.txt'
        @(
            'VM v1.4.2 MAINTENANCE FAILURE',
            ('Generated: '+(Get-Date -Format o)),
            ('Error: '+$FailureMessage),
            ('PreSnapshot: '+$PreSnapshot)
        ) | Set-Content -LiteralPath $failurePath -Encoding UTF8
        Copy-Item -LiteralPath $failurePath -Destination (Join-Path $Downloads 'VM_MAINTENANCE_FAILURE.txt') -Force
    } catch {}
    Restore-Pre142 -Snapshot $PreSnapshot
    Write-Host "[ROLLBACK] Pre-v1.4.2 platform state restored." -ForegroundColor Yellow
    if($TranscriptStarted){ try { Stop-Transcript | Out-Null } catch {} }
    exit 2
}
