param(
    [int]$IntervalSeconds = 15,
    [double]$MinScore = 45,
    [double]$AlertScore = 65,
    [int]$EventLimit = 250,
    [int]$CandidateLimit = 500,
    [int]$FullRefreshMinutes = 60,
    [int]$ExpiryRefreshMinutes = 10,
    [int]$LogRetentionDays = 30
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$LogDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogRetentionDays = [Math]::Max(1, [Math]::Min($LogRetentionDays, 365))
Get-ChildItem -Path $LogDir -Filter 'match_engine_*.log' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$LogRetentionDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$LogFile = Join-Path $LogDir ("match_engine_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher (py) was not found.'
}

$IntervalSeconds = [Math]::Max(10, [Math]::Min($IntervalSeconds, 300))
$MinScore = [Math]::Max(0, [Math]::Min($MinScore, 100))
$AlertScore = [Math]::Max($MinScore, [Math]::Min($AlertScore, 100))
$EventLimit = [Math]::Max(1, [Math]::Min($EventLimit, 2000))
$CandidateLimit = [Math]::Max(10, [Math]::Min($CandidateLimit, 2000))
$FullRefreshMinutes = [Math]::Max(5, [Math]::Min($FullRefreshMinutes, 1440))
$ExpiryRefreshMinutes = [Math]::Max(1, [Math]::Min($ExpiryRefreshMinutes, 360))

"[$(Get-Date -Format o)] Universal Search Match Engine v2 starting" | Add-Content -Path $LogFile
("interval={0} min_score={1} alert_score={2} event_limit={3} candidate_limit={4} full_refresh_minutes={5} expiry_refresh_minutes={6} retention_days={7}" -f `
    $IntervalSeconds, $MinScore, $AlertScore, $EventLimit, $CandidateLimit, $FullRefreshMinutes, $ExpiryRefreshMinutes, $LogRetentionDays) | Add-Content -Path $LogFile

& py .\match_daemon_v2.py `
    --interval $IntervalSeconds `
    --min-score $MinScore `
    --alert-score $AlertScore `
    --event-limit $EventLimit `
    --candidate-limit $CandidateLimit `
    --full-refresh-minutes $FullRefreshMinutes `
    --expiry-refresh-minutes $ExpiryRefreshMinutes *>> $LogFile
$Code = $LASTEXITCODE
"[$(Get-Date -Format o)] Match Engine v2 exited code=$Code" | Add-Content -Path $LogFile
exit $Code
