$ErrorActionPreference="Stop"
Set-Location -LiteralPath $PSScriptRoot
Write-Host "This action archives and then removes only the verified nested legacy Relationship Manager folder." -ForegroundColor Yellow
py .\vm.py relationship-cleanup
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
$confirm=Read-Host 'Type CLEANUP_RELATIONSHIP_LEGACY to approve archive + removal'
if($confirm -ne 'CLEANUP_RELATIONSHIP_LEGACY'){
    Write-Host 'No changes made.' -ForegroundColor Yellow
    exit 1
}
py .\vm.py relationship-cleanup --apply
exit $LASTEXITCODE
