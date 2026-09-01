$ErrorActionPreference="Stop"
Set-Location -LiteralPath $PSScriptRoot

$PreSnapshot=$env:VM_PREINSTALL_SNAPSHOT

function Restore-VM14Preinstall {
    param([string]$Snapshot)
    if(-not $Snapshot -or -not (Test-Path -LiteralPath $Snapshot -PathType Container)){
        Write-Host "[ROLLBACK] No usable pre-install snapshot path was supplied." -ForegroundColor Yellow
        return
    }
    Write-Host "[ROLLBACK] Restoring previous platform-managed files..." -ForegroundColor Yellow
    $restoreTool=Join-Path $PSScriptRoot 'tools\restore_vm_snapshot.py'
    if(Test-Path -LiteralPath $restoreTool){
        py $restoreTool --root $PSScriptRoot --snapshot $Snapshot --apply --no-safety-backup | Out-Host
        if($LASTEXITCODE -eq 0){
            Write-Host "[ROLLBACK] Verified standalone snapshot restore completed." -ForegroundColor Green
            return
        }
        Write-Host "[ROLLBACK] Standalone restore failed; using PowerShell fallback." -ForegroundColor Yellow
    }
    $items=@(
        'vm.py','VM_PROJECT.json','pyproject.toml','shared',
        'config\vm_platform.json','VM_CONTROL.bat',
        'START_VM_MANAGED.bat','ENABLE_VM_AUTOSTART.ps1','ENABLE_VM_AUTOSTART.bat',
        'DISABLE_VM_AUTOSTART.ps1','DISABLE_VM_AUTOSTART.bat',
        'bots\Admin_Command_Centre','bots\Universal_Search','bots\VM_Guard'
    )
    foreach($i in $items){
        $dest=Join-Path $PSScriptRoot $i
        $src=Join-Path $Snapshot $i
        if(Test-Path -LiteralPath $dest){
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
        if(Test-Path -LiteralPath $src){
            $parent=Split-Path $dest -Parent
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
        }
    }
    try {
        Set-Location -LiteralPath $PSScriptRoot
        py .\vm.py start-managed --apply | Out-Host
    } catch {}
}

function Run-Step {
    param([string]$Label,[scriptblock]$Action,[switch]$Critical)
    Write-Host ""
    Write-Host $Label -ForegroundColor Cyan
    & $Action
    $code=$LASTEXITCODE
    if($null -eq $code){$code=0}
    if($code -ne 0){
        if($Critical){ throw "$Label failed with exit code $code" }
        Write-Host "[WARN] $Label returned exit code $code." -ForegroundColor Yellow
    }
    return $code
}

try {
    Write-Host ""
    Write-Host "================================================================"
    Write-Host " VM ECOSYSTEM v1.4.0 - RECOVERY + RELIABILITY ROLLOUT"
    Write-Host "================================================================"

    Run-Step "[1/17] Initialising/migrating VM Platform..." { py .\vm.py init } -Critical
    Write-Host ""
    Write-Host "[2/17] Refreshing manifests + inventory..." -ForegroundColor Cyan
    py .\vm.py manifests --refresh --write
    if($LASTEXITCODE -ne 0){ throw "Manifest refresh failed." }
    py .\vm.py inventory
    if($LASTEXITCODE -ne 0){ throw "Inventory refresh failed." }

    Write-Host ""
    Write-Host "[3/17] Recovering pre-v1.3 Search/Guard Telegram entrypoints safely..." -ForegroundColor Cyan
    py .\vm.py legacy-recovery
    $previewCode=$LASTEXITCODE
    if($previewCode -eq 0){
        py .\vm.py legacy-recovery --apply
        if($LASTEXITCODE -ne 0){
            Write-Host "[WARN] Legacy recovery apply was rejected by its safety gate." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[WARN] Legacy recovery preview found something unsafe; no legacy code was restored." -ForegroundColor Yellow
    }

    Run-Step "[4/17] Auditing legacy compatibility without rewriting legacy core.py..." {
        py .\tools\repair_legacy_compat.py
    }

    Write-Host ""
    Write-Host "[5/17] Ensuring Search/Guard declared dependencies are installed..." -ForegroundColor Cyan
    foreach($req in @(
        '.\bots\Universal_Search\requirements.txt',
        '.\bots\VM_Guard\requirements.txt'
    )){
        if(Test-Path -LiteralPath $req){
            py -m pip install -r $req
            if($LASTEXITCODE -ne 0){
                Write-Host "[WARN] Dependency install had an issue for $req; validation will decide whether it is critical." -ForegroundColor Yellow
            }
        }
    }

    Run-Step "[6/17] Synchronising shared registries..." { py .\vm.py registry sync }
    Run-Step "[7/17] Rebuilding Universal Search index..." { py .\vm.py search-refresh } -Critical
    Run-Step "[8/17] Running initial VM Guard pass..." { py .\vm.py guard }

    Write-Host ""
    Write-Host "[9/17] Generating Relationship Manager cleanup plan (NO DELETE)..." -ForegroundColor Cyan
    py .\vm.py relationship-cleanup
    if($LASTEXITCODE -ne 0){Write-Host "[WARN] Cleanup plan requires review; no deletion attempted." -ForegroundColor Yellow}

    Run-Step "[10/17] Merging VM Git exclusions safely..." { py .\tools\merge_vm_gitignore.py }
    Run-Step "[11/17] Running Git tracked-file security audit..." { py .\vm.py git-audit }

    Write-Host ""
    Write-Host "[12/17] Installing/updating Ruff + uv developer tools when available..." -ForegroundColor Cyan
    py .\vm.py dev-tools --apply
    if($LASTEXITCODE -ne 0){
        Write-Host "[WARN] Developer tools could not be installed; production rollout continues." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "[13/17] Running full ecosystem validation..." -ForegroundColor Cyan
    py .\vm.py validate-all
    $validationCode=$LASTEXITCODE
    if($validationCode -ne 0){
        throw "Critical VM v1.4 validation failed."
    }

    Write-Host ""
    Write-Host "[14/17] Starting managed services in background..." -ForegroundColor Cyan
    py .\vm.py start-managed --apply
    if($LASTEXITCODE -ne 0){Write-Host "[WARN] One or more services did not start; runtime recovery will retry." -ForegroundColor Yellow}
    Start-Sleep -Seconds 8

    Write-Host ""
    Write-Host "[15/17] Enabling passive Windows logon startup..." -ForegroundColor Cyan
    try { & ".\ENABLE_VM_AUTOSTART.ps1" }
    catch { Write-Host "[WARN] Autostart registration failed: $($_.Exception.Message)" -ForegroundColor Yellow }

    Write-Host ""
    Write-Host "[16/17] Verifying live managed runtime..." -ForegroundColor Cyan
    py .\vm.py runtime-check --require-autostart --require-legacy-components
    $runtimeCode=$LASTEXITCODE
    if($runtimeCode -ne 0){
        Write-Host "[WARN] First runtime check failed. Running one recovery pass..." -ForegroundColor Yellow
        py .\vm.py supervise --apply | Out-Host
        Start-Sleep -Seconds 6
        py .\vm.py runtime-check --require-autostart --require-legacy-components
        $runtimeCode=$LASTEXITCODE
    }

    Write-Host ""
    Write-Host "[17/17] Final live diagnostics + readable handoff..." -ForegroundColor Cyan
    py .\vm.py runtime | Out-Host
    py .\vm.py storage | Out-Host
    py .\vm.py support | Out-Host
    py .\vm.py support-text | Out-Host

    try {
        $downloads=Join-Path $env:USERPROFILE 'Downloads'
        $latest=Get-ChildItem '.\state\support\VM_SUPPORT_*.zip' -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($latest){Copy-Item $latest.FullName (Join-Path $downloads 'VM_SUPPORT_LATEST.zip') -Force}

        $latestTxt=Get-ChildItem '.\state\support\VM_SUPPORT_READABLE_*.txt' -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($latestTxt){Copy-Item $latestTxt.FullName (Join-Path $downloads 'VM_SUPPORT_READABLE.txt') -Force}
    } catch {
        Write-Host "[WARN] Could not copy final diagnostics to Downloads." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host " VM ECOSYSTEM v1.4.0 INSTALLED + VALIDATED" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "Admin Command Centre : v0.4.0"
    Write-Host "Universal Search     : v1.1.0 hybrid wrapper"
    Write-Host "VM Guard             : v1.1.0 hybrid wrapper"
    Write-Host "Relationship cleanup : PREVIEW ONLY - no nested folder deleted"
    Write-Host ("Readable diagnostics : " + (Join-Path $env:USERPROFILE 'Downloads\VM_SUPPORT_READABLE.txt'))
    if($runtimeCode -ne 0){
        Write-Host "[NOTE] Static validation passed, but live runtime still needs review." -ForegroundColor Yellow
    } else {
        Write-Host "[OK] Live managed runtime verification passed." -ForegroundColor Green
    }
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[VM v1.4 INSTALL FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Restore-VM14Preinstall -Snapshot $PreSnapshot
    Write-Host "[ROLLBACK] Previous platform-managed files restored where available." -ForegroundColor Yellow
    exit 2
}
