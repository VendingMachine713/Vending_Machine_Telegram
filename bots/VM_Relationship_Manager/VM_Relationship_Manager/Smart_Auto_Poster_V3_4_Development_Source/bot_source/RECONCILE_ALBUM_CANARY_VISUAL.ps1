param(
    [string]$Approval = '',
    [int]$ExpectedJobId = 0
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$TaskName = 'VM Smart Auto Poster Album Canary Retry'
$ReceiptDir = Join-Path $Root 'runtime\canary'
$ReceiptPath = Join-Path $ReceiptDir 'album_canary_visual_ok.json'
New-Item -ItemType Directory -Path $ReceiptDir -Force | Out-Null

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SMART AUTO POSTER - RECONCILE VISUALLY CONFIRMED CANARY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'This performs NO Telegram send.' -ForegroundColor Green
Write-Host 'It stops/deletes the canary retry task before touching queue state.' -ForegroundColor Yellow
Write-Host ''

# Stop/delete any pending automatic retry before reconciliation. A visually observed
# album must never be resent just because Telegram acknowledgement was ambiguous.
try { & schtasks.exe /End /TN $TaskName *> $null } catch { }
try { & schtasks.exe /Delete /TN $TaskName /F *> $null } catch { }
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue }
} catch { }
Write-Host '[OK] Automatic canary retry task stopped/removed if present.' -ForegroundColor Green

$raw = & py .\app.py canary-status --campaign-id album_canary_01 2>&1
if ($LASTEXITCODE -ne 0) { $raw | Out-Host; throw 'Album canary status unavailable.' }
$status = (($raw -join "`n") | ConvertFrom-Json)
$status | ConvertTo-Json -Depth 8 | Out-Host

if ($ExpectedJobId -gt 0 -and [int]$status.id -ne $ExpectedJobId) {
    throw "Latest canary is job #$($status.id), not explicitly approved job #$ExpectedJobId. Reconciliation blocked."
}
if ($status.status -eq 'sent') {
    Write-Host '[INFO] Latest canary is already SENT; no queue mutation required.' -ForegroundColor Green
} else {
    if ($status.status -notin @('retry','uncertain','deferred','pending')) {
        throw "Canary is '$($status.status)' and cannot be visually reconciled."
    }
    $confirm = $Approval
    if (-not $confirm) { $confirm = Read-Host 'Type ALBUM_VISUALLY_CONFIRMED_SENT only if this exact album is visibly present in LIVE_TEST' }
    if ($confirm -ne 'ALBUM_VISUALLY_CONFIRMED_SENT') {
        Write-Host '[CANCELLED] No reconciliation performed.' -ForegroundColor Yellow
        exit 0
    }
    & py .\app.py canary-reconcile-sent --campaign-id album_canary_01 --job-id $status.id --confirmation ALBUM_VISUALLY_CONFIRMED_SENT | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Visual canary reconciliation failed.' }
}

$afterRaw = & py .\app.py canary-status --campaign-id album_canary_01 2>&1
if ($LASTEXITCODE -ne 0) { $afterRaw | Out-Host; throw 'Post-reconciliation canary status unavailable.' }
$after = (($afterRaw -join "`n") | ConvertFrom-Json)
if ($after.status -ne 'sent') { throw "Canary did not reconcile to SENT; final status is '$($after.status)'." }
if ($ExpectedJobId -gt 0 -and [int]$after.id -ne $ExpectedJobId) { throw 'Canary job changed during reconciliation.' }

$receipt = [ordered]@{
    schema_version = 2
    confirmed_at = [DateTimeOffset]::Now.ToString('o')
    campaign_id = 'album_canary_01'
    job_id = [int]$after.id
    status = 'sent'
    group_id = [long]$after.group_id
    group_name = $after.group_name
    content_id = $after.content_id
    telegram_message_ids = $after.telegram_message_ids
    confirmation = 'ALBUM_OK'
    reconciliation = 'visual_confirmation_after_ambiguous_ack'
    telegram_send_performed = $false
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' CANARY RECONCILED SAFELY - NO RESEND' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host "Job              : #$($after.id) SENT"
Write-Host "Visual receipt   : $ReceiptPath"
Write-Host 'Telegram send    : NONE performed by reconciliation'
Write-Host 'Scheduled retry  : REMOVED'
Write-Host 'Production       : UNCHANGED / INACTIVE'
