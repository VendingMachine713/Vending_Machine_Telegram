$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - SAFE MAIN PRODUCTION SETUP' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This configures the campaign, schedule, content tags and album canary.' -ForegroundColor DarkGray
Write-Host 'It DOES NOT activate production and DOES NOT send Telegram messages.' -ForegroundColor Yellow
Write-Host ''

$contents = 'main_ad_01_fixed,main_ad_02,main_ad_03,main_ad_04,main_ad_05'

& py .\app.py production-bootstrap `
    --campaign-id main_production_01 `
    --name 'Main Production Campaign' `
    --collection all_approved `
    --contents $contents `
    --exclude-tags live_test `
    --rotation least_recent `
    --interval-minutes 240 `
    --priority 100 `
    --reuse-minutes 1440 `
    --conflict-gap-minutes 60 `
    --spread-minutes 0 `
    --category production `
    --content-tags 'production,main_ads' `
    --canary-campaign album_canary_01 `
    --canary-collection live_test
if ($LASTEXITCODE -ne 0) { throw 'Production bootstrap failed.' }

Write-Host ''
Write-Host '> Production readiness...' -ForegroundColor DarkGray
& py .\app.py production-readiness main_production_01 --collection all_approved
if ($LASTEXITCODE -ne 0) { throw 'Production readiness failed.' }

Write-Host ''
Write-Host '> Album canary readiness...' -ForegroundColor DarkGray
& py .\app.py production-readiness album_canary_01 --collection live_test
if ($LASTEXITCODE -ne 0) { throw 'Album canary readiness failed.' }

Write-Host ''
Write-Host '> 24-hour pre-activation simulation...' -ForegroundColor DarkGray
& py .\app.py simulate --hours 24 --campaign main_production_01 --include-inactive
if ($LASTEXITCODE -ne 0) { throw 'Schedule simulation failed.' }

Write-Host ''
Write-Host '> Database integrity...' -ForegroundColor DarkGray
& py .\app.py integrity
if ($LASTEXITCODE -ne 0) { throw 'SQLite integrity failed.' }

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' MAIN PRODUCTION SETUP READY - NO SEND PERFORMED' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Campaign        : main_production_01 (READY / inactive)'
Write-Host 'Target          : all_approved'
Write-Host 'Exclude         : live_test'
Write-Host 'Variants        : 5'
Write-Host 'Rotation        : least_recent'
Write-Host 'Interval        : 240 minutes (4 hours)'
Write-Host 'Album canary    : album_canary_01 (READY / inactive)'
Write-Host 'Next gate       : explicit canary SEND approval'
