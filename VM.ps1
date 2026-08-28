param(
    [Parameter(Position=0)]
    [ValidateSet(
        "start",
        "stop",
        "restart",
        "status",
        "doctor",
        "test",
        "inspect"
    )]
    [string]$Command = "status"
)

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BotsRoot = Join-Path $Root "bots"
$LogsRoot = Join-Path $Root "shared\logs"

New-Item -ItemType Directory -Force -Path $LogsRoot | Out-Null

# ==================================================
# EXPLICIT BOT REGISTRY
# No heuristic launcher guessing.
# ==================================================

$Registry = @(
    [PSCustomObject]@{
        Name     = "Admin_Command_Centre"
        Type     = "python"
        Launcher = "main.py"
    },
    [PSCustomObject]@{
        Name     = "Smart_Auto_Poster_V2"
        Type     = "powershell"
        Launcher = "RUN_SERVICE.ps1"
    },
    [PSCustomObject]@{
        Name     = "Universal_Search"
        Type     = "python"
        Launcher = "main.py"
    },
    [PSCustomObject]@{
        Name     = "VM_Guard"
        Type     = "python"
        Launcher = "main.py"
    },
    [PSCustomObject]@{
        Name     = "VM_Relationship_Manager"
        Type     = "powershell"
        Launcher = "START_VM_RELATIONSHIPS.ps1"
    }
)

function Get-BotFolder {
    param($Bot)

    Join-Path $BotsRoot $Bot.Name
}

function Get-LauncherPath {
    param($Bot)

    Join-Path (Get-BotFolder $Bot) $Bot.Launcher
}

function Get-BotProcesses {
    param($Bot)

    $folder = Get-BotFolder $Bot

    # Match persistent processes whose command lines originate
    # from the bot's permanent project folder.
    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ProcessId -ne $PID -and
                $_.CommandLine -and
                $_.CommandLine.IndexOf(
                    $folder,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            }
    )
}

function Get-BotStatus {
    param($Bot)

    $launcherPath = Get-LauncherPath $Bot
    $processes = @(Get-BotProcesses $Bot)

    [PSCustomObject]@{
        Bot       = $Bot.Name
        Running   = if ($processes.Count -gt 0) { "YES" } else { "NO" }
        Processes = $processes.Count
        Launcher  = if (Test-Path $launcherPath) {
                        $Bot.Launcher
                    }
                    else {
                        "NOT FOUND"
                    }
    }
}

function Start-Bot {
    param($Bot)

    $folder = Get-BotFolder $Bot
    $launcherPath = Get-LauncherPath $Bot

    if (-not (Test-Path $launcherPath)) {
        Write-Host "[SKIP] $($Bot.Name): launcher missing -> $($Bot.Launcher)" -ForegroundColor Yellow
        return
    }

    $existing = @(Get-BotProcesses $Bot)

    if ($existing.Count -gt 0) {
        Write-Host "[RUNNING] $($Bot.Name) already has $($existing.Count) process(es)." -ForegroundColor Green
        return
    }

    try {

        if ($Bot.Type -eq "python") {

            $stdout = Join-Path $LogsRoot "$($Bot.Name)_stdout.log"
            $stderr = Join-Path $LogsRoot "$($Bot.Name)_stderr.log"

            Start-Process `
                -FilePath "py.exe" `
                -ArgumentList @("-u", "`"$launcherPath`"") `
                -WorkingDirectory $folder `
                -RedirectStandardOutput $stdout `
                -RedirectStandardError $stderr `
                -WindowStyle Hidden

        }
        elseif ($Bot.Type -eq "powershell") {

            $stdout = Join-Path $LogsRoot "$($Bot.Name)_stdout.log"
            $stderr = Join-Path $LogsRoot "$($Bot.Name)_stderr.log"

            Start-Process `
                -FilePath "powershell.exe" `
                -ArgumentList @(
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    "`"$launcherPath`""
                ) `
                -WorkingDirectory $folder `
                -RedirectStandardOutput $stdout `
                -RedirectStandardError $stderr `
                -WindowStyle Hidden
        }

        Start-Sleep -Milliseconds 800

        $running = @(Get-BotProcesses $Bot)

        if ($running.Count -gt 0) {
            Write-Host "[STARTED] $($Bot.Name)" -ForegroundColor Green
        }
        else {
            Write-Host "[EXITED] $($Bot.Name) did not remain running." -ForegroundColor Yellow
            Write-Host "         Check shared\logs\$($Bot.Name)_stderr.log" -ForegroundColor DarkYellow
        }

    }
    catch {
        Write-Host "[FAIL] $($Bot.Name): $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Stop-Bot {
    param($Bot)

    $processes = @(Get-BotProcesses $Bot)

    if ($processes.Count -eq 0) {
        Write-Host "[STOPPED] $($Bot.Name) already inactive."
        return
    }

    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            Write-Host "[WARN] Could not stop PID $($process.ProcessId)" -ForegroundColor Yellow
        }
    }

    Start-Sleep -Milliseconds 500

    $remaining = @(Get-BotProcesses $Bot)

    if ($remaining.Count -eq 0) {
        Write-Host "[STOPPED] $($Bot.Name)" -ForegroundColor Green
    }
    else {
        Write-Host "[WARN] $($Bot.Name) still has $($remaining.Count) process(es)." -ForegroundColor Yellow
    }
}

function Show-Status {

    $rows = foreach ($bot in $Registry) {
        Get-BotStatus $bot
    }

    $rows | Format-Table -AutoSize
}

function Run-Doctor {

    Write-Host "=== VM DOCTOR ===" -ForegroundColor Cyan

    $checks = @(
        @{
            Name = "Project root"
            Pass = Test-Path $Root
            Info = $Root
        },
        @{
            Name = "bots folder"
            Pass = Test-Path $BotsRoot
            Info = $BotsRoot
        },
        @{
            Name = "Python launcher"
            Pass = $null -ne (Get-Command py.exe -ErrorAction SilentlyContinue)
            Info = "py.exe"
        },
        @{
            Name = "Git"
            Pass = $null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)
            Info = "git"
        },
        @{
            Name = "PowerShell"
            Pass = $true
            Info = $PSVersionTable.PSVersion.ToString()
        }
    )

    foreach ($check in $checks) {

        if ($check.Pass) {
            Write-Host "[PASS] $($check.Name) - $($check.Info)" -ForegroundColor Green
        }
        else {
            Write-Host "[FAIL] $($check.Name) - $($check.Info)" -ForegroundColor Red
        }
    }

    Write-Host "`n=== BOT LAUNCHERS ===" -ForegroundColor Cyan

    foreach ($bot in $Registry) {

        $launcher = Get-LauncherPath $bot

        if (Test-Path $launcher) {
            Write-Host "[PASS] $($bot.Name): $($bot.Launcher)" -ForegroundColor Green
        }
        else {
            Write-Host "[FAIL] $($bot.Name): missing $($bot.Launcher)" -ForegroundColor Red
        }
    }

    Write-Host ""
    Show-Status
}

function Run-SmokeTest {

    Write-Host "=== VM SMOKE TEST ===" -ForegroundColor Cyan

    foreach ($bot in $Registry) {

        $launcher = Get-LauncherPath $bot

        if (-not (Test-Path $launcher)) {
            Write-Host "[FAIL] $($bot.Name): launcher missing" -ForegroundColor Red
            continue
        }

        if ($Bot.Type -eq "python") {
            py -m py_compile $launcher

            if ($LASTEXITCODE -eq 0) {
                Write-Host "[PASS] $($bot.Name): Python entrypoint" -ForegroundColor Green
            }
            else {
                Write-Host "[FAIL] $($bot.Name): Python syntax" -ForegroundColor Red
            }
        }
        else {
            Write-Host "[PASS] $($bot.Name): $($bot.Launcher)" -ForegroundColor Green
        }
    }
}

function Inspect-Bots {

    Write-Host "=== VM BOT INSPECTION ===" -ForegroundColor Cyan

    foreach ($bot in $Registry) {

        $folder = Get-BotFolder $bot

        Write-Host "`n--- $($bot.Name) ---" -ForegroundColor Cyan

        if (-not (Test-Path $folder)) {
            Write-Host "[MISSING FOLDER]" -ForegroundColor Red
            continue
        }

        Write-Host "Registered launcher: $($bot.Launcher)"

        Get-ChildItem `
            -LiteralPath $folder `
            -File `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -in ".py",".ps1",".bat",".cmd"
            } |
            Select-Object Name,Length |
            Format-Table -AutoSize
    }
}

switch ($Command) {

    "start" {
        foreach ($bot in $Registry) {
            Start-Bot $bot
        }

        Write-Host ""
        Show-Status
    }

    "stop" {
        foreach ($bot in $Registry) {
            Stop-Bot $bot
        }

        Write-Host ""
        Show-Status
    }

    "restart" {
        foreach ($bot in $Registry) {
            Stop-Bot $bot
        }

        Start-Sleep -Seconds 1

        foreach ($bot in $Registry) {
            Start-Bot $bot
        }

        Write-Host ""
        Show-Status
    }

    "status" {
        Show-Status
    }

    "doctor" {
        Run-Doctor
    }

    "test" {
        Run-SmokeTest
    }

    "inspect" {
        Inspect-Bots
    }
}
