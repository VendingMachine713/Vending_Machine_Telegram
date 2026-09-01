param(
    [string]$Approval = ''
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - GUARDED PRODUCTION ACTIVATION' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This enables scheduled posting but performs NO immediate Post Now.' -ForegroundColor Yellow
Write-Host 'The 4-hour interval is re-armed from activation time before the campaign is enabled.' -ForegroundColor Yellow

if ($Approval -ne 'ACTIVATE') {
    $Approval = Read-Host 'Type ACTIVATE to enable scheduled production posting'
}
if ($Approval.ToUpperInvariant() -ne 'ACTIVATE') {
    Write-Host '[CANCELLED] Production remains inactive.' -ForegroundColor Yellow
    exit 0
}

Write-Host '> Applying requested 4-hour production interval while campaign is inactive...' -ForegroundColor DarkGray
& py .\app.py schedule main_production_01 --interval-minutes 240 --start-in-minutes 240 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Could not apply the requested 4-hour production interval.' }

$preRaw = @(& py .\app.py go-live-readiness main_production_01 --collection all_approved --expected-destinations 32 --expected-variants 5 --require-album-items 10 --expected-interval-minutes 240 2>&1)
if ($LASTEXITCODE -ne 0) { $preRaw | Out-Host; throw 'Go-live readiness failed. Activation blocked.' }
$pre = (($preRaw -join "`n") | ConvertFrom-Json)
if (-not $pre.ok) { throw 'Go-live readiness did not return OK.' }
Write-Host '[OK] Strict go-live readiness passed.' -ForegroundColor Green

Write-Host '> Verifying both Telegram user sessions (NO SEND)...' -ForegroundColor DarkGray
& py .\app.py accounts-check | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Telegram account authorization check failed. Activation blocked.' }

Write-Host '> Re-arming 4-hour production schedule from activation time...' -ForegroundColor DarkGray
$armRaw = @(& py .\app.py schedule-rearm main_production_01 2>&1)
if ($LASTEXITCODE -ne 0) { $armRaw | Out-Host; throw 'Schedule re-arm failed. Activation blocked.' }
$arm = (($armRaw -join "`n") | ConvertFrom-Json)
$next = [DateTimeOffset]::Parse([string]$arm.next_run_at)
$delay = ($next - [DateTimeOffset]::UtcNow).TotalMinutes
if ($delay -lt 230 -or $delay -gt 250) { throw "Re-armed first run is not approximately 4 hours away: $([math]::Round($delay,1)) minutes." }
Write-Host "[OK] First production cycle armed for $($next.ToString('o')) (~$([math]::Round($delay,1)) minutes from now)." -ForegroundColor Green

& py .\app.py campaign-state main_production_01 active | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Campaign activation failed.' }

$postRaw = @(& py .\app.py production-readiness main_production_01 --collection all_approved --json-only 2>&1)
if ($LASTEXITCODE -ne 0) { $postRaw | Out-Host; throw 'Post-activation readiness failed.' }
$post = (($postRaw -join "`n") | ConvertFrom-Json)
if (-not $post.enabled -or $post.state -ne 'active') { throw 'Production did not remain ACTIVE after activation.' }
if ([int]$post.selected -ne 32 -or [int]$post.media_delivery.photo_destinations -ne 32 -or [int]$post.media_delivery.text_destinations -ne 0) {
    throw 'Post-activation delivery invariant failed.'
}
if ([int]$post.active_queue_jobs -ne 0) { throw 'Unexpected production queue jobs exist immediately after activation.' }

Write-Host ''
Write-Host '[OK] main_production_01 is ACTIVE.' -ForegroundColor Green
Write-Host "First scheduled cycle: $($next.ToString('o'))" -ForegroundColor Green
Write-Host 'Immediate send: NONE.' -ForegroundColor Green
