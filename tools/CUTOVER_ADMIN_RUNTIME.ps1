param(
    [string]$Root,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'

if ($Approval -ne 'CUTOVER_ADMIN_RUNTIME') {
    throw 'Approval missing. Re-run with -Approval CUTOVER_ADMIN_RUNTIME.'
}

if (-not $Root) {
    $Root = (git rev-parse --show-toplevel).Trim()
}
$Root = (Resolve-Path $Root).Path
$poster = Join-Path $Root 'bots\Smart_Auto_Poster_V2'
$admin = Join-Path $Root 'bots\Admin_Command_Centre'
$posterApp = Join-Path $poster 'app.py'
$posterSettings = Join-Path $poster 'smart_autoposter\settings.py'
$adminEnv = Join-Path $admin '.env'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $Root ("backups\admin-runtime-cutover-$stamp")
New-Item -ItemType Directory -Force -Path $backup | Out-Null

function Read-EnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $t = $line.Trim()
        if ($t -match ('^' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Get-Role([string]$CommandLine) {
    if ($CommandLine -match 'Admin_Command_Centre') { return 'ADMIN_COMMAND_CENTRE' }
    if ($CommandLine -match 'Smart_Auto_Poster_V2|smart_autoposter') { return 'SMART_AUTO_POSTER' }
    return $null
}

function Get-RoleRoots([string]$Role) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $matches = @($all | Where-Object {
        $_.CommandLine -and
        $_.Name -match '^(python(w)?|py|powershell|pwsh)\.exe$' -and
        (Get-Role ($_.CommandLine + '')) -eq $Role
    })
    $ids = @{}
    foreach ($m in $matches) { $ids[[int]$m.ProcessId] = $true }
    return @($matches | Where-Object { -not $ids.ContainsKey([int]$_.ParentProcessId) } | Sort-Object ProcessId)
}

function Get-DescendantRows([int]$RootProcessId) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $rows = @()
    $queue = @([pscustomobject]@{ Id=$RootProcessId; Depth=0 })
    while ($queue.Count -gt 0) {
        $current = $queue[0]
        if ($queue.Count -gt 1) { $queue = @($queue[1..($queue.Count-1)]) } else { $queue = @() }
        foreach ($child in @($all | Where-Object { [int]$_.ParentProcessId -eq [int]$current.Id })) {
            $row = [pscustomobject]@{ Id=[int]$child.ProcessId; Depth=([int]$current.Depth + 1); Name=$child.Name }
            $rows += $row
            $queue += $row
        }
    }
    return @($rows)
}

function Stop-ProcessTree([int]$ProcessId, [string]$Label) {
    Write-Host "Stopping $Label root PID $ProcessId ..."
    $desc = @(Get-DescendantRows $ProcessId | Sort-Object Depth -Descending)
    foreach ($row in $desc) {
        if (Get-Process -Id $row.Id -ErrorAction SilentlyContinue) {
            Stop-Process -Id $row.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 150
        }
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(12)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 400
    }
    Write-Host "$Label root is still present; using final taskkill fallback."
    & taskkill.exe /PID $ProcessId /F | Out-Null
    Start-Sleep -Seconds 2
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw "$Label root PID $ProcessId is still running after explicit descendant-first forced termination."
    }
}

function Start-ExactCommand([string]$CommandLine, [string]$WorkingDirectory, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { throw "$Label command line is empty." }
    $result = ([wmiclass]'Win32_Process').Create($CommandLine, $WorkingDirectory, $null)
    if ($result.ReturnValue -ne 0) {
        throw "$Label restart failed. Win32_Process.Create return value: $($result.ReturnValue)"
    }
    Write-Host "$Label restart requested successfully (new PID $($result.ProcessId))."
}

function Invoke-PosterJson([string]$Command) {
    $py = (Get-Command py.exe -ErrorAction Stop).Source
    $stdout = Join-Path $env:TEMP ('vm-cutover-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('vm-cutover-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $p = Start-Process -FilePath $py -ArgumentList @('-3.12','app.py',$Command) -WorkingDirectory $poster -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = ''
        if (Test-Path $stdout) { $out = Get-Content $stdout -Raw -ErrorAction SilentlyContinue }
        if ($p.ExitCode -ne 0) {
            $err = ''
            if (Test-Path $stderr) { $err = Get-Content $stderr -Raw -ErrorAction SilentlyContinue }
            throw "app.py $Command failed with exit code $($p.ExitCode). $err"
        }
        return ($out | ConvertFrom-Json)
    } finally {
        Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-PosterText([string]$Command) {
    $py = (Get-Command py.exe -ErrorAction Stop).Source
    $stdout = Join-Path $env:TEMP ('vm-cutover-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('vm-cutover-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $p = Start-Process -FilePath $py -ArgumentList @('-3.12','app.py',$Command) -WorkingDirectory $poster -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = ''
        if (Test-Path $stdout) { $out += (Get-Content $stdout -Raw -ErrorAction SilentlyContinue) }
        if (Test-Path $stderr) {
            $err = Get-Content $stderr -Raw -ErrorAction SilentlyContinue
            if ($err) { $out += "`n" + $err }
        }
        if ($p.ExitCode -ne 0) { throw "app.py $Command failed with exit code $($p.ExitCode)." }
        return $out.Trim()
    } finally {
        Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
}

function Test-AdminBotApi([string]$Token) {
    if ([string]::IsNullOrWhiteSpace($Token)) { return $false }
    try {
        $response = Invoke-RestMethod -Method Get -Uri ("https://api.telegram.org/bot{0}/getMe" -f $Token) -TimeoutSec 15
        return [bool]$response.ok
    } catch {
        return $false
    }
}

Write-Host '============================================================'
Write-Host ' VM ADMIN / SMART AUTO POSTER - CONTROLLED RUNTIME CUTOVER'
Write-Host '============================================================'
Write-Host 'Mode: RESUMABLE / FAIL-CLOSED'
Write-Host 'Approval: VERIFIED'
Write-Host "Root: $Root"
Write-Host 'Campaign activation: NEVER REQUESTED'
Write-Host 'Admin mutations: MUST REMAIN DISABLED'
Write-Host ''

Write-Host '[1/7] Fail-closed safety verification'
if (-not (Test-Path -LiteralPath $posterApp -PathType Leaf)) { throw 'Smart Auto Poster app.py not found.' }
if (-not (Test-Path -LiteralPath $posterSettings -PathType Leaf)) { throw 'Smart Auto Poster settings.py not found.' }
if (-not (Test-Path -LiteralPath $adminEnv -PathType Leaf)) { throw 'Admin Command Centre .env not found.' }
$settingsText = Get-Content -LiteralPath $posterSettings -Raw
if (-not [regex]::IsMatch($settingsText,'(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False')) { throw 'Embedded Smart Auto Poster admin guard is not forced off.' }
$adminToken = Read-EnvValue $adminEnv 'VM_ADMIN_BOT_TOKEN'
$adminIds = Read-EnvValue $adminEnv 'VM_ADMIN_USER_IDS'
$allowMutations = Read-EnvValue $adminEnv 'VM_ADMIN_ALLOW_MUTATIONS'
if ([string]::IsNullOrWhiteSpace($adminToken)) { throw 'VM_ADMIN_BOT_TOKEN is missing.' }
if ([string]::IsNullOrWhiteSpace($adminIds)) { throw 'VM_ADMIN_USER_IDS is missing.' }
if (($allowMutations + '').ToLowerInvariant() -ne 'false') { throw 'VM_ADMIN_ALLOW_MUTATIONS must be false for cutover.' }
$capacity = Invoke-PosterJson 'queue-capacity'
if ([int]$capacity.active_total -ne 0) { throw "Poster has active work (active_total=$($capacity.active_total)); refusing runtime cutover." }
Write-Host 'Embedded admin guard: OFF'
Write-Host 'Admin config ownership: READY'
Write-Host 'Admin mutations: DISABLED'
Write-Host 'Poster active queue: 0'
Write-Host ''

Write-Host '[2/7] Capture live state and recovery commands'
$posterRoots = @(Get-RoleRoots 'SMART_AUTO_POSTER')
$adminRoots = @(Get-RoleRoots 'ADMIN_COMMAND_CENTRE')
if ($posterRoots.Count -ne 1) { throw "Expected exactly one Smart Auto Poster root so its exact launch command can be preserved; found $($posterRoots.Count)." }
if ($adminRoots.Count -gt 1) { throw "Expected zero or one Admin Command Centre root; found $($adminRoots.Count)." }
$posterRoot = $posterRoots[0]
$posterCommand = $posterRoot.CommandLine
$adminCommand = $null
if ($adminRoots.Count -eq 1) {
    $adminCommand = $adminRoots[0].CommandLine
} else {
    $py = (Get-Command py.exe -ErrorAction Stop).Source
    $adminCommand = ('"{0}" -3.12 main.py' -f $py)
}
@(
    "timestamp=$([DateTimeOffset]::Now.ToString('o'))",
    "poster_pid=$($posterRoot.ProcessId)",
    "admin_roots_before=$($adminRoots.Count)",
    'poster_command_captured=yes',
    "admin_command_source=$(if($adminRoots.Count -eq 1){'live'}else{'canonical-main.py'})",
    'secret_values_written=no'
) | Set-Content -LiteralPath (Join-Path $backup 'runtime-state.txt') -Encoding UTF8
Write-Host "Rollback/state folder: $backup"
Write-Host "Poster root PID: $($posterRoot.ProcessId)"
Write-Host "Admin roots before resume: $($adminRoots.Count)"
Write-Host ''

Write-Host '[3/7] Ensure standalone Admin Command Centre is stopped'
if ($adminRoots.Count -eq 1) {
    Stop-ProcessTree ([int]$adminRoots[0].ProcessId) 'Admin Command Centre'
} else {
    Write-Host 'Admin Command Centre is already stopped from the prior partial cutover.'
}
Start-Sleep -Seconds 1
if (@(Get-RoleRoots 'ADMIN_COMMAND_CENTRE').Count -ne 0) { throw 'Admin Command Centre process still present after stop phase.' }
Write-Host 'Standalone Admin Command Centre stopped.'
Write-Host ''

Write-Host '[4/7] Restart Smart Auto Poster to unload embedded admin from memory'
Stop-ProcessTree ([int]$posterRoot.ProcessId) 'Smart Auto Poster'
Start-Sleep -Seconds 1
if (@(Get-RoleRoots 'SMART_AUTO_POSTER').Count -ne 0) { throw 'Smart Auto Poster process still present after stop.' }
Start-ExactCommand $posterCommand $poster 'Smart Auto Poster'
Start-Sleep -Seconds 8
$posterAfter = @(Get-RoleRoots 'SMART_AUTO_POSTER')
if ($posterAfter.Count -ne 1) { throw "Expected exactly one Smart Auto Poster root after restart; found $($posterAfter.Count)." }
Write-Host "Smart Auto Poster running with one root PID $($posterAfter[0].ProcessId)."
Write-Host ''

Write-Host '[5/7] Verify poster before starting standalone admin'
$capacityAfter = Invoke-PosterJson 'queue-capacity'
if ([int]$capacityAfter.active_total -ne 0) { throw "Unexpected active queue after poster restart (active_total=$($capacityAfter.active_total))." }
$health = Invoke-PosterText 'health'
if ($health -notmatch '\[READY\]') { throw 'Poster health did not report READY after restart.' }
if ($health -notmatch 'admin control bot\s+optional / not configured') { throw 'Poster health does not confirm embedded admin is unconfigured.' }
Write-Host 'Poster health: READY'
Write-Host 'Embedded admin runtime ownership: NOT CONFIGURED'
Write-Host 'Poster active queue after restart: 0'
Write-Host ''

Write-Host '[6/7] Restart exactly one standalone Admin Command Centre'
Start-ExactCommand $adminCommand $admin 'Admin Command Centre'
Start-Sleep -Seconds 8
$adminAfter = @(Get-RoleRoots 'ADMIN_COMMAND_CENTRE')
if ($adminAfter.Count -ne 1) { throw "Expected exactly one Admin Command Centre root after restart; found $($adminAfter.Count)." }
Write-Host "Admin Command Centre running with one root PID $($adminAfter[0].ProcessId)."
$apiOk = Test-AdminBotApi $adminToken
Write-Host "Telegram Bot API getMe: $($(if($apiOk){'OK'}else{'UNVERIFIED'}))"
Write-Host ''

Write-Host '[7/7] Final separation verification'
$posterFinal = @(Get-RoleRoots 'SMART_AUTO_POSTER')
$adminFinal = @(Get-RoleRoots 'ADMIN_COMMAND_CENTRE')
$capacityFinal = Invoke-PosterJson 'queue-capacity'
if ($posterFinal.Count -ne 1) { throw "Final poster root count is $($posterFinal.Count), expected 1." }
if ($adminFinal.Count -ne 1) { throw "Final admin root count is $($adminFinal.Count), expected 1." }
if ([int]$capacityFinal.active_total -ne 0) { throw 'Final poster active queue is not zero.' }
if (-not [regex]::IsMatch((Get-Content -LiteralPath $posterSettings -Raw),'(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False')) { throw 'Final embedded-admin guard verification failed.' }
Write-Host ''
Write-Host 'RUNTIME CUTOVER: PASSED'
Write-Host 'Smart Auto Poster roots: 1'
Write-Host 'Admin Command Centre roots: 1'
Write-Host 'Embedded poster admin: DISABLED / UNCONFIGURED'
Write-Host 'Admin mutations: DISABLED'
Write-Host 'Campaign activation: NOT PERFORMED'
Write-Host 'Poster active queue: 0'
Write-Host "Rollback/state folder: $backup"
Write-Host ''
Write-Host 'Copy this entire output back to ChatGPT. Secret values are never printed.'
