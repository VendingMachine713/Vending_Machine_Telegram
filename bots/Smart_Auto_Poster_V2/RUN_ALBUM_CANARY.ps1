param(
    [string]$Approval = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - ALBUM CANARY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This sends ONE real Telegram post to the LIVE_TEST canary only.' -ForegroundColor Yellow
Write-Host 'The canary is photo-mode so the 10-photo media-group path is exercised.' -ForegroundColor Yellow
Write-Host ''

# Never create a duplicate while an earlier approved canary is unresolved.
$existingRaw = & py .\app.py canary-status --campaign-id album_canary_01 2>$null
if ($LASTEXITCODE -eq 0) {
    $existing = (($existingRaw -join "`n") | ConvertFrom-Json)
    if ($existing.status -in @('pending','retry','deferred')) {
        Write-Host "[SAFE] Existing canary job #$($existing.id) is '$($existing.status)'. No new job will be created." -ForegroundColor Yellow
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\RESUME_ALBUM_CANARY.ps1 AUTO
        exit $LASTEXITCODE
    }
}

& py .\app.py production-readiness album_canary_01 --collection live_test
if ($LASTEXITCODE -ne 0) { throw 'Album canary readiness failed. No send performed.' }

& py .\app.py preview album_canary_01
if ($LASTEXITCODE -ne 0) { throw 'Album canary preview failed. No send performed.' }

$confirm = $Approval
if (-not $confirm) {
    $confirm = Read-Host 'Type SEND to send ONE album to LIVE_TEST'
}
if ($confirm.ToUpperInvariant() -ne 'SEND') {
    Write-Host '[CANCELLED] No Telegram message was sent.' -ForegroundColor Yellow
    exit 0
}

$activated = $false
try {
    & py .\app.py campaign-state album_canary_01 active
    if ($LASTEXITCODE -ne 0) { throw 'Could not activate album canary.' }
    $activated = $true

    & py .\app.py post-now album_canary_01
    if ($LASTEXITCODE -ne 0) { throw 'Could not enqueue album canary.' }

    & py .\app.py worker --once
    if ($LASTEXITCODE -ne 0) { throw 'Canary worker failed.' }
}
finally {
    if ($activated) {
        & py .\app.py campaign-state album_canary_01 paused | Out-Host
    }
}

Write-Host ''
Write-Host '> Canary queue result...' -ForegroundColor DarkGray
& py .\app.py queue --campaign album_canary_01 --limit 10

$statusRaw = & py .\app.py canary-status --campaign-id album_canary_01
$status = (($statusRaw -join "`n") | ConvertFrom-Json)
if ($status.status -eq 'sent') {
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ' CANARY SENT - CAMPAIGN PAUSED AGAIN' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host 'Verify in Telegram that the test post is one 10-photo album/media-group with the expected caption.'
    exit 0
}

if ($status.status -in @('retry','deferred','pending')) {
    Write-Host ''
    Write-Host '[INFO] Telegram deferred the approved canary. Scheduling the SAME queue job for its stored retry time.' -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\RESUME_ALBUM_CANARY.ps1 AUTO
    exit $LASTEXITCODE
}

throw "Canary ended in '$($status.status)'. Production remains inactive."
