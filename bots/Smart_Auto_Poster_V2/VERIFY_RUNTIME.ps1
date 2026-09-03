param(
    [int]$TimeoutSeconds = 420,
    [int]$PollSeconds = 10
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = 'VendingMachine Smart Auto Poster V2'
$Lock = Join-Path $Root 'runtime\telegram_runtime.lock\owner.json'
$Deadline = (Get-Date).AddSeconds([Math]::Max(30, $TimeoutSeconds))
$PollSeconds = [Math]::Max(2, $PollSeconds)

function Read-Watchdog {
    $raw = @(& py .\app.py watchdog --require service --require scheduler --require worker --json-only 2>&1)
    $exitCode = $LASTEXITCODE
    $text = ($raw -join "`n")
    try { $data = $text | ConvertFrom-Json } catch { $data = $null }
    return [pscustomobject]@{ ExitCode=$exitCode; Text=$text; Data=$data }
}

Push-Location $Root
try {
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' SMART AUTO POSTER - MANAGED RUNTIME VERIFICATION' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    while ((Get-Date) -lt $Deadline -and -not (Test-Path -LiteralPath $Lock)) {
        Start-Sleep -Seconds $PollSeconds
    }
    if (-not (Test-Path -LiteralPath $Lock)) {
        throw "Runtime lock was not established within $TimeoutSeconds seconds."
    }
    Write-Host '[OK] Runtime lock established.' -ForegroundColor Green

    $last = $null
    while ((Get-Date) -lt $Deadline) {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task -or [string]$task.State -ne 'Running') {
            throw "Managed task is not running (state=$($task.State))."
        }
        $last = Read-Watchdog
        if ($last.Data) {
            $coreProblems = @($last.Data.problems)
            if ($coreProblems.Count -eq 0) {
                Write-Host $last.Text
                Write-Host '[OK] Core service, scheduler and worker heartbeats are fresh.' -ForegroundColor Green
                & py .\app.py watchdog --require admin_bot --json-only
                if ($LASTEXITCODE -eq 0) {
                    Write-Host '[OK] Admin Bot heartbeat is fresh.' -ForegroundColor Green
                    exit 0
                }
                $network = $last.Data.heartbeats.network
                if ($network -and -not $network.stale -and $network.status -eq 'error') {
                    Write-Host '[DEGRADED_NETWORK] Core runtime is healthy; Telegram/network is unavailable and outbound work is safely paused.' -ForegroundColor Yellow
                    exit 0
                }
            }
        }
        Start-Sleep -Seconds $PollSeconds
    }

    if ($last) { Write-Host $last.Text }
    $network = if ($last -and $last.Data) { $last.Data.heartbeats.network } else { $null }
    if ($network -and -not $network.stale -and $network.status -eq 'error') {
        Write-Host '[DEGRADED_NETWORK] Runtime is alive but Telegram/network remains unavailable; queue is preserved.' -ForegroundColor Yellow
        exit 0
    }
    throw "Runtime did not reach a verifiable core-ready state within $TimeoutSeconds seconds."
} finally {
    Pop-Location
}
