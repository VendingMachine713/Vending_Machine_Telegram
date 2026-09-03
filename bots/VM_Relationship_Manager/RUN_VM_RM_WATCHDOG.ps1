$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$runtime = Join-Path $PSScriptRoot "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$stopFile = Join-Path $runtime "watchdog.stop"

$master = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logDir = Join-Path $master "shared\logs\VM_Relationship_Manager"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$watchdogLog = Join-Path $logDir "watchdog.log"

function Write-WatchdogLog([string]$Message) {
    try {
        if ((Test-Path -LiteralPath $watchdogLog) -and (Get-Item -LiteralPath $watchdogLog).Length -gt 1000000) {
            $tail = Get-Content -LiteralPath $watchdogLog -Tail 500 -ErrorAction SilentlyContinue
            [System.IO.File]::WriteAllLines($watchdogLog, [string[]]$tail)
        }
        $line = "$(Get-Date -Format o) | $Message"
        Add-Content -LiteralPath $watchdogLog -Value $line -Encoding UTF8
    }
    catch { }
}

$delaySeconds = 60
Write-WatchdogLog "watchdog started"

while ($true) {
    if (Test-Path -LiteralPath $stopFile) {
        Write-WatchdogLog "stop sentinel detected; watchdog exiting"
        exit 0
    }

    $started = Get-Date
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "START_VM_RELATIONSHIPS.ps1")
        $rc = $LASTEXITCODE
        if ($null -eq $rc) { $rc = 1 }
    }
    catch {
        $rc = 99
        Write-WatchdogLog ("starter exception: " + $_.Exception.GetType().Name)
    }
    $runSeconds = ((Get-Date) - $started).TotalSeconds

    if (Test-Path -LiteralPath $stopFile) {
        Write-WatchdogLog "stop sentinel detected after child exit; watchdog exiting"
        exit 0
    }

    if ($runSeconds -ge 300) {
        # A process that stayed healthy for 5+ minutes earns a reset to fast recovery.
        $delaySeconds = 60
    }
    elseif ($rc -ne 0) {
        $delaySeconds = [Math]::Min(900, [Math]::Max(60, $delaySeconds * 2))
    }
    else {
        # Exit 0 commonly means the single-instance guard found a manual copy.
        $delaySeconds = 60
    }

    Write-WatchdogLog "Relationship Manager exited code=$rc runtime_seconds=$([Math]::Round($runSeconds,1)); retry_seconds=$delaySeconds"
    Start-Sleep -Seconds $delaySeconds
}
