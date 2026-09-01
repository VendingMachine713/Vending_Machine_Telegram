param(
    [string]$Approval = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$ReceiptDir = Join-Path $Root 'runtime\canary'
$ReceiptPath = Join-Path $ReceiptDir 'album_canary_visual_ok.json'
New-Item -ItemType Directory -Path $ReceiptDir -Force | Out-Null

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - CONFIRM ALBUM CANARY VISUALLY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This records YOUR visual Telegram verification. It sends nothing.' -ForegroundColor Green
Write-Host ''

$raw = & py .\app.py canary-status --campaign-id album_canary_01 2>&1
if ($LASTEXITCODE -ne 0) { $raw | Out-Host; throw 'Album canary status unavailable.' }
$status = (($raw -join "`n") | ConvertFrom-Json)
$status | ConvertTo-Json -Depth 8 | Out-Host
if ($status.status -ne 'sent') {
    throw "Album canary is '$($status.status)', not SENT. Visual approval cannot be recorded yet."
}

Write-Host ''
Write-Host 'Confirm in Telegram that:' -ForegroundColor Yellow
Write-Host '  - all 10 photos are present' -ForegroundColor Yellow
Write-Host '  - they appear as ONE album/media group' -ForegroundColor Yellow
Write-Host '  - the expected caption is attached correctly' -ForegroundColor Yellow
$confirm = $Approval
if (-not $confirm) { $confirm = Read-Host 'Type ALBUM_OK only after visually checking Telegram' }
if ($confirm.ToUpperInvariant() -ne 'ALBUM_OK') {
    Write-Host '[CANCELLED] Visual canary approval was NOT recorded.' -ForegroundColor Yellow
    exit 0
}

$receipt = [ordered]@{
    schema_version = 1
    confirmed_at = [DateTimeOffset]::Now.ToString('o')
    campaign_id = 'album_canary_01'
    job_id = $status.id
    status = $status.status
    group_id = $status.group_id
    group_name = $status.group_name
    content_id = $status.content_id
    telegram_message_ids = $status.telegram_message_ids
    confirmation = 'ALBUM_OK'
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
Write-Host "[OK] Visual album canary receipt recorded: $ReceiptPath" -ForegroundColor Green
Write-Host '[SAFE] Production remains unchanged/inactive.' -ForegroundColor Green
