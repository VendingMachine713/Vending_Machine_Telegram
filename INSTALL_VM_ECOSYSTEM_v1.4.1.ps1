$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$PreSnapshot=$env:VM_PREINSTALL_SNAPSHOT

function Restore-Pre141 {
    param([string]$Snapshot)
    if(-not $Snapshot -or -not (Test-Path -LiteralPath $Snapshot -PathType Container)){
        Write-Host '[ROLLBACK] Pre-v1.4.1 snapshot unavailable.' -ForegroundColor Yellow
        return
    }
    Write-Host '[ROLLBACK] Restoring pre-v1.4.1 platform-managed state...' -ForegroundColor Yellow
    $items=@(
        'vm.py','VM_PROJECT.json','pyproject.toml','shared','tools','tests','docs',
        'README_VM_PLATFORM.md','CHANGELOG_VM_PLATFORM.md','APPLY_RELATIONSHIP_CLEANUP.ps1','APPLY_RELATIONSHIP_CLEANUP.bat',
        'config\vm_platform.json','VM_CONTROL.bat','.gitignore','START_VM_MANAGED.bat',
        'ENABLE_VM_AUTOSTART.ps1','ENABLE_VM_AUTOSTART.bat','DISABLE_VM_AUTOSTART.ps1','DISABLE_VM_AUTOSTART.bat',
        'bots\Admin_Command_Centre','bots\Universal_Search','bots\VM_Guard','bots\VM_Relationship_Manager'
    )
    foreach($i in $items){
        $dst=Join-Path $PSScriptRoot $i; $src=Join-Path $Snapshot $i
        if(Test-Path -LiteralPath $dst){Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $src){
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        }
    }
    $sapDst=Join-Path $PSScriptRoot 'bots\Smart_Auto_Poster_V2'
    $sapSrc=Join-Path $Snapshot 'bots\Smart_Auto_Poster_V2'
    foreach($rel in @('CONTROL_PANEL.ps1','GO_LIVE.ps1','master_updater\APPLY_UPDATE.ps1')){
        $dst=Join-Path $sapDst $rel; $src=Join-Path $sapSrc $rel
        if(Test-Path -LiteralPath $dst){Remove-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $src){
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    try { py .\vm.py init | Out-Host; py .\vm.py start-managed --apply | Out-Host } catch {}
}

function Require-Step {
    param([string]$Label,[scriptblock]$Action)
    Write-Host ''; Write-Host $Label -ForegroundColor Cyan
    & $Action
    if($LASTEXITCODE -ne 0){throw "$Label failed with exit code $LASTEXITCODE"}
}

try {
    Write-Host ''
    Write-Host '================================================================' -ForegroundColor Cyan
    Write-Host ' VM ECOSYSTEM v1.4.1 - LIVE RECONCILIATION' -ForegroundColor Cyan
    Write-Host '================================================================' -ForegroundColor Cyan
    Write-Host 'Safety: no Auto Poster activation, no new canary, no Telegram send.'

    Write-Host ''; Write-Host '[0/12] Stopping managed control services for clean code reload...' -ForegroundColor Cyan
    foreach($svc in @('Admin_Command_Centre','Universal_Search','VM_Guard')){
        try { py .\vm.py stop $svc --apply | Out-Host } catch {}
    }
    Start-Sleep -Seconds 2

    Require-Step '[1/12] Initialising platform...' { py .\vm.py init }

    Write-Host ''; Write-Host '[2/12] Refreshing manifests + inventory...' -ForegroundColor Cyan
    py .\vm.py manifests --refresh --write; if($LASTEXITCODE -ne 0){throw 'Manifest refresh failed.'}
    py .\vm.py inventory; if($LASTEXITCODE -ne 0){throw 'Inventory refresh failed.'}

    Write-Host ''; Write-Host '[3/12] Smart Auto Poster drift preview + test-gated repair...' -ForegroundColor Cyan
    py .\vm.py sap-repair; if($LASTEXITCODE -ne 0){throw 'Smart Auto Poster repair preview could not find a safe local recovery path.'}
    py .\vm.py sap-repair --apply; if($LASTEXITCODE -ne 0){throw 'Smart Auto Poster repair failed and was rolled back.'}

    Write-Host ''; Write-Host '[4/12] Re-verifying Relationship Manager nested cleanup safety (PREVIEW ONLY)...' -ForegroundColor Cyan
    py .\vm.py relationship-cleanup | Out-Host
    if($LASTEXITCODE -ne 0){Write-Host '[WARN] Relationship cleanup is not currently eligible. No deletion attempted.' -ForegroundColor Yellow}

    Write-Host ''; Write-Host '[5/12] Refreshing registry + local search...' -ForegroundColor Cyan
    py .\vm.py registry sync; if($LASTEXITCODE -ne 0){throw 'Registry sync failed.'}
    py .\vm.py search-refresh; if($LASTEXITCODE -ne 0){throw 'Universal Search refresh failed.'}

    Require-Step '[6/12] Refreshing VM Guard + resolving obsolete alerts...' { py .\vm.py guard }

    Write-Host ''; Write-Host '[7/12] Git safety + storage diagnostics...' -ForegroundColor Cyan
    py .\tools\merge_vm_gitignore.py | Out-Host
    py .\vm.py git-audit | Out-Host
    if($LASTEXITCODE -ne 0){throw 'Git audit found a critical tracked credential/session file.'}
    py .\vm.py storage | Out-Host

    Require-Step '[8/12] Running ALL canonical ecosystem tests + validation...' { py .\vm.py validate-all }

    Write-Host ''; Write-Host '[9/12] Starting managed services in background...' -ForegroundColor Cyan
    py .\vm.py start-managed --apply | Out-Host
    Start-Sleep -Seconds 8

    Write-Host ''; Write-Host '[10/12] Ensuring passive Windows logon startup...' -ForegroundColor Cyan
    $registered=$false
    try {
        $raw=@(& py .\vm.py autostart-status 2>&1); $obj=(($raw -join "`n")|ConvertFrom-Json); $registered=[bool]$obj.registered
    } catch {}
    if(-not $registered){ & .\ENABLE_VM_AUTOSTART.ps1 }
    py .\vm.py autostart-status | Out-Host

    Write-Host ''; Write-Host '[11/12] Verifying managed + legacy runtime...' -ForegroundColor Cyan
    py .\vm.py runtime-check --require-autostart --require-legacy-components
    if($LASTEXITCODE -ne 0){
        Write-Host '[RECOVERY] First runtime check failed; applying one supervisor recovery pass.' -ForegroundColor Yellow
        py .\vm.py supervise --apply | Out-Host; Start-Sleep -Seconds 6
        py .\vm.py runtime-check --require-autostart --require-legacy-components
        if($LASTEXITCODE -ne 0){throw 'Live runtime verification failed after recovery pass.'}
    }

    Write-Host ''; Write-Host '[12/12] Final Doctor + Guard + support handoff...' -ForegroundColor Cyan
    py .\vm.py doctor | Out-Host; if($LASTEXITCODE -ne 0){throw 'VM Doctor reported a failure.'}
    py .\vm.py guard | Out-Host
    py .\vm.py runtime | Out-Host
    py .\vm.py support | Out-Host
    py .\vm.py support-text | Out-Host

    $downloads=Join-Path $env:USERPROFILE 'Downloads'
    try {
        $zip=Get-ChildItem '.\state\support\VM_SUPPORT_*.zip' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($zip){Copy-Item $zip.FullName (Join-Path $downloads 'VM_SUPPORT_LATEST.zip') -Force}
        $txt=Get-ChildItem '.\state\support\VM_SUPPORT_READABLE_*.txt' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($txt){Copy-Item $txt.FullName (Join-Path $downloads 'VM_SUPPORT_READABLE.txt') -Force}
    } catch { Write-Host '[WARN] Could not copy final support files to Downloads.' -ForegroundColor Yellow }

    Write-Host ''
    Write-Host '================================================================' -ForegroundColor Green
    Write-Host ' VM ECOSYSTEM v1.4.1 INSTALLED + VALIDATED' -ForegroundColor Green
    Write-Host '================================================================' -ForegroundColor Green
    Write-Host 'Auto Poster: operational drift test-gated/repaired or already clean.'
    Write-Host 'Relationship Manager: cleanup re-verified; nested folder NOT deleted by this installer.'
    Write-Host 'VM Guard: historical burst warning refreshed against 15-minute window.'
    Write-Host 'Managed services/autostart: verified.'
    Write-Host ('Upload: '+(Join-Path $downloads 'VM_SUPPORT_READABLE.txt'))
    exit 0
}
catch {
    Write-Host ''; Write-Host "[VM v1.4.1 FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Restore-Pre141 -Snapshot $PreSnapshot
    Write-Host '[ROLLBACK] Pre-v1.4.1 state restored where applicable.' -ForegroundColor Yellow
    exit 2
}
