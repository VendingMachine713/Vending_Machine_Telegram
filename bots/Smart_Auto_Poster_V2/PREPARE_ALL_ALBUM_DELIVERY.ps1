$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - PREPARE ALL-ALBUM DELIVERY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This changes selected production destination delivery mode from TEXT to PHOTO.' -ForegroundColor Yellow
Write-Host 'It does NOT activate production, enqueue jobs, or send Telegram messages.' -ForegroundColor Green
Write-Host ''
$raw = & py .\app.py album-delivery-plan --campaign-id main_production_01 2>&1
if ($LASTEXITCODE -ne 0) { $raw | Out-Host; throw 'Could not build album delivery plan.' }
$plan = (($raw -join "`n") | ConvertFrom-Json)
$plan | ConvertTo-Json -Depth 8 | Out-Host
if ([int]$plan.text_destinations -eq 0) {
    Write-Host '[OK] All selected production destinations are already photo-mode. No changes needed.' -ForegroundColor Green
    exit 0
}
Write-Host ''
Write-Host "This will change $($plan.text_destinations) selected production destination(s) to photo mode." -ForegroundColor Yellow
Write-Host 'The LIVE_TEST canary is not part of main_production_01/all_approved and is not changed.' -ForegroundColor Yellow
$confirm = Read-Host 'Type APPLY_PHOTO_MODE to make this configuration change'
if ($confirm -ne 'APPLY_PHOTO_MODE') {
    Write-Host '[CANCELLED] No destination modes changed.' -ForegroundColor Yellow
    exit 0
}
& py .\app.py album-delivery-apply --campaign-id main_production_01 --confirm APPLY_PHOTO_MODE
if ($LASTEXITCODE -ne 0) { throw 'Album delivery mode migration failed.' }
& py .\app.py production-readiness main_production_01 --collection all_approved
if ($LASTEXITCODE -ne 0) { throw 'Post-migration production readiness failed.' }
Write-Host ''
Write-Host '[OK] ALL selected production destinations are now configured for album/photo delivery.' -ForegroundColor Green
Write-Host 'Production remains READY / INACTIVE. No Telegram send was performed.' -ForegroundColor Green
