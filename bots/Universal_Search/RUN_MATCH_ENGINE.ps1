param(
    [int]$IntervalSeconds = 30,
    [double]$MinScore = 45,
    [double]$AlertScore = 65,
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

$IntervalSeconds = [Math]::Max(10, [Math]::Min($IntervalSeconds, 600))
$MinScore = [Math]::Max(0, [Math]::Min($MinScore, 100))
$AlertScore = [Math]::Max($MinScore, [Math]::Min($AlertScore, 100))

"[$(Get-Date -Format o)] Universal Search Match Engine starting" | Add-Content -Path $LogFile
"interval=$IntervalSeconds min_score=$MinScore alert_score=$AlertScore retention_days=$LogRetentionDays" | Add-Content -Path $LogFile

& py .\match_daemon.py --interval $IntervalSeconds --min-score $MinScore --alert-score $AlertScore *>> $LogFile
$Code = $LASTEXITCODE
"[$(Get-Date -Format o)] Match Engine exited code=$Code" | Add-Content -Path $LogFile
exit $Code
