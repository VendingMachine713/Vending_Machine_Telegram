$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd'
$Log = Join-Path $LogDir "service_$Stamp.log"
$MaxRestarts = 3
$attempt = 0
while ($attempt -lt $MaxRestarts) {
    $attempt++
    "`n[$(Get-Date -Format o)] Smart Auto Poster V3 service starting (attempt $attempt/$MaxRestarts)" | Out-File -FilePath $Log -Append -Encoding utf8
    & py .\app.py run *>> $Log
    $code = $LASTEXITCODE
    "[$(Get-Date -Format o)] Service exited with code $code" | Out-File -FilePath $Log -Append -Encoding utf8
    if ($code -eq 0) { break }
    if ($attempt -lt $MaxRestarts) {
        "[$(Get-Date -Format o)] Waiting 60 seconds before bounded restart" | Out-File -FilePath $Log -Append -Encoding utf8
        Start-Sleep -Seconds 60
    }
}
if ($code -ne 0) {
    "[$(Get-Date -Format o)] Restart limit reached; manual attention required." | Out-File -FilePath $Log -Append -Encoding utf8
    exit $code
}
