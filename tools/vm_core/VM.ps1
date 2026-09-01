param(
    [Parameter(Position=0)]
    [ValidateSet("status","start","stop","restart-failed","doctor","backup","test","inspect","help")]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BotsRoot = Join-Path $Root "bots"
$BackupRoot = Join-Path $Root "backups"

function Get-Bots {
    if (!(Test-Path $BotsRoot)) { return @() }
    @(Get-ChildItem $BotsRoot -Directory | Sort-Object Name)
}
function Is-Disabled($BotPath) { return (Test-Path (Join-Path $BotPath ".vm_disabled")) }

function Find-Launcher($BotPath) {
    if (Is-Disabled $BotPath) { return $null }
    $preferred = @(
        "START.ps1","start.ps1","RUN_SERVICE.ps1","run.ps1","RUN.ps1",
        "START_VM_RELATIONSHIPS.ps1","START_BOT.ps1",
        "START.bat","start.bat","RUN.bat","run.bat",
        "START.cmd","start.cmd","RUN.cmd","run.cmd",
        "main.py","bot.py","app.py"
    )
    foreach ($name in $preferred) {
        $p = Join-Path $BotPath $name
        if (Test-Path $p) { return $p }
    }
    $candidate = Get-ChildItem $BotPath -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^(start|run).*?\.(ps1|bat|cmd|py)$" } |
        Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
    return $null
}
function Get-BotProcesses($BotPath) {
    $escaped = [regex]::Escape($BotPath)
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $escaped })
}
function Invoke-Launcher($Launcher,$WorkingDir) {
    if ($Launcher.EndsWith(".ps1")) {
        Start-Process powershell.exe -WorkingDirectory $WorkingDir -ArgumentList @(
            "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$Launcher`""
        ) | Out-Null
    } elseif ($Launcher.EndsWith(".py")) {
        Start-Process py.exe -WorkingDirectory $WorkingDir -ArgumentList @("`"$Launcher`"") | Out-Null
    } elseif ($Launcher.EndsWith(".bat") -or $Launcher.EndsWith(".cmd")) {
        Start-Process cmd.exe -WorkingDirectory $WorkingDir -ArgumentList @("/c","`"$Launcher`"") | Out-Null
    }
}
function Show-Status {
    $rows = foreach ($bot in Get-Bots) {
        $disabled = Is-Disabled $bot.FullName
        $launcher = Find-Launcher $bot.FullName
        $procs = Get-BotProcesses $bot.FullName
        [pscustomobject]@{
            Bot = $bot.Name
            State = if ($disabled) {"DISABLED"} elseif ($procs.Count -gt 0) {"RUNNING"} else {"STOPPED"}
            Processes = $procs.Count
            Launcher = if ($disabled) {"CONFIG REQUIRED"} elseif ($launcher) {[IO.Path]::GetFileName($launcher)} else {"NOT FOUND"}
        }
    }
    if ($rows) { $rows | Format-Table -AutoSize } else { Write-Host "[WARN] No bot folders found." }
}
function Start-Bots {
    foreach ($bot in Get-Bots) {
        if (Is-Disabled $bot.FullName) { Write-Host "[SKIP] $($bot.Name): disabled until configured"; continue }
        if ((Get-BotProcesses $bot.FullName).Count -gt 0) { Write-Host "[OK] $($bot.Name) already running"; continue }
        $launcher = Find-Launcher $bot.FullName
        if (!$launcher) { Write-Host "[SKIP] $($bot.Name): no recognised launcher"; continue }
        try { Invoke-Launcher $launcher $bot.FullName; Write-Host "[STARTED] $($bot.Name)" }
        catch { Write-Host "[FAIL] $($bot.Name): $($_.Exception.Message)" }
    }
}
function Stop-Bots {
    foreach ($bot in Get-Bots) {
        $procs = Get-BotProcesses $bot.FullName
        if ($procs.Count -eq 0) { Write-Host "[OK] $($bot.Name) already stopped"; continue }
        foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} }
        Write-Host "[STOPPED] $($bot.Name)"
    }
}
function Restart-Failed {
    foreach ($bot in Get-Bots) {
        if (Is-Disabled $bot.FullName) { continue }
        if ((Get-BotProcesses $bot.FullName).Count -eq 0) {
            $launcher = Find-Launcher $bot.FullName
            if ($launcher) {
                try { Invoke-Launcher $launcher $bot.FullName; Write-Output "[RECOVERED] $($bot.Name) $(Get-Date -Format s)" }
                catch { Write-Output "[RECOVERY FAILED] $($bot.Name): $($_.Exception.Message)" }
            }
        }
    }
}
function Run-Doctor {
    Write-Host "=== VM DOCTOR ==="
    $checks = @(
        @{Name="Project root"; Ok=(Test-Path $Root); Info=$Root},
        @{Name="bots folder"; Ok=(Test-Path $BotsRoot); Info=$BotsRoot},
        @{Name="Python launcher"; Ok=[bool](Get-Command py -ErrorAction SilentlyContinue); Info="py"},
        @{Name="Git"; Ok=[bool](Get-Command git -ErrorAction SilentlyContinue); Info="git"},
        @{Name="PowerShell"; Ok=$true; Info=$PSVersionTable.PSVersion.ToString()}
    )
    foreach ($c in $checks) {
        $tag = if ($c.Ok) {"PASS"} else {"FAIL"}
        Write-Host "[$tag] $($c.Name) - $($c.Info)"
    }
    Write-Host ""
    Show-Status
}
function Backup-Project {
    if (!(Test-Path $BackupRoot)) { New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $dest = Join-Path $BackupRoot "VM_backup_$stamp.zip"
    $tmp = Join-Path $env:TEMP "vm_backup_$stamp"
    New-Item -ItemType Directory $tmp -Force | Out-Null
    $exclude = @("backups",".git","__pycache__",".venv","venv")
    Get-ChildItem $Root -Force | Where-Object { $_.Name -notin $exclude } | ForEach-Object {
        Copy-Item $_.FullName $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    Compress-Archive -Path (Join-Path $tmp "*") -DestinationPath $dest -Force
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Backup created: $dest"
}
function Test-Project {
    Write-Host "=== VM SMOKE TEST ==="
    foreach ($bot in Get-Bots) {
        if (Is-Disabled $bot.FullName) { Write-Host "[READY] $($bot.Name): installed, config required"; continue }
        $launcher = Find-Launcher $bot.FullName
        if ($launcher) { Write-Host "[PASS] $($bot.Name): $([IO.Path]::GetFileName($launcher))" }
        else { Write-Host "[WARN] $($bot.Name): launcher not detected" }
    }
}
function Inspect-Missing {
    Write-Host "=== BOT INSPECTION ==="
    foreach ($bot in Get-Bots) {
        Write-Host "$($bot.Name): " -NoNewline
        if (Is-Disabled $bot.FullName) { Write-Host "INSTALLED / CONFIG REQUIRED"; continue }
        $l=Find-Launcher $bot.FullName
        if ($l) { Write-Host ([IO.Path]::GetFileName($l)) } else { Write-Host "NO LAUNCHER" }
    }
}

switch ($Command) {
    "status" { Show-Status }
    "start" { Start-Bots }
    "stop" { Stop-Bots }
    "restart-failed" { Restart-Failed }
    "doctor" { Run-Doctor }
    "backup" { Backup-Project }
    "test" { Test-Project }
    "inspect" { Inspect-Missing }
    default {
        Write-Host "VM CONTROL: status | start | stop | restart-failed | doctor | backup | test | inspect"
    }
}
