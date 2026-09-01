$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$snapshot=Get-ChildItem '.\backups\pre_v1_4_ecosystem_*' -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if(-not $snapshot){
    Write-Host '[ERROR] No pre-v1.4 safety snapshot found.' -ForegroundColor Red
    exit 2
}
Write-Host ('[INFO] Restoring: '+$snapshot.FullName) -ForegroundColor Yellow
foreach($svc in @('Admin_Command_Centre','Universal_Search','VM_Guard')){
    try { py .\vm.py stop $svc --apply | Out-Null } catch {}
}
py .\tools\restore_vm_snapshot.py --root $root --snapshot $snapshot.FullName --apply
if($LASTEXITCODE -ne 0){
    Write-Host '[ERROR] Verified restore failed.' -ForegroundColor Red
    exit $LASTEXITCODE
}
Set-Location -LiteralPath $root
try { py .\vm.py start-managed --apply | Out-Host } catch {}
Write-Host '[OK] Previous platform-managed files restored and verified.' -ForegroundColor Green
