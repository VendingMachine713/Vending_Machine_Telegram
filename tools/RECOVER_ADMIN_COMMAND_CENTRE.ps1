param(
    [string]$Root,
    [string]$Approval
)

$ErrorActionPreference = 'Stop'

if ($Approval -ne 'RECOVER_ADMIN_COMMAND_CENTRE') {
    throw 'Approval missing. Re-run with -Approval RECOVER_ADMIN_COMMAND_CENTRE.'
}

if (-not $Root) { $Root = (git rev-parse --show-toplevel).Trim() }
$Root = (Resolve-Path $Root).Path
$poster = Join-Path $Root 'bots\Smart_Auto_Poster_V2'
$admin = Join-Path $Root 'bots\Admin_Command_Centre'
$posterSettings = Join-Path $poster 'smart_autoposter\settings.py'
$adminEnv = Join-Path $admin '.env'
$adminMain = Join-Path $admin 'main.py'

function Read-EnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $t = $line.Trim()
        if ($t -match ('^' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) { return $Matches[1].Trim() }
    }
    return $null
}

function Get-AdminRoots {
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $matches = @($all | Where-Object {
        $_.CommandLine -and $_.Name -match '^(python(w)?|py)\.exe$' -and $_.CommandLine -match 'Admin_Command_Centre'
    })
    $ids = @{}
    foreach ($m in $matches) { $ids[[int]$m.ProcessId] = $true }
    return @($matches | Where-Object { -not $ids.ContainsKey([int]$_.ParentProcessId) } | Sort-Object ProcessId)
}

function Invoke-PosterJson([string]$Command) {
    $py = (Get-Command py.exe -ErrorAction Stop).Source
    $stdout = Join-Path $env:TEMP ('vm-admin-recover-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('vm-admin-recover-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $p = Start-Process -FilePath $py -ArgumentList @('-3.12','app.py',$Command) -WorkingDirectory $poster -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = if (Test-Path $stdout) { Get-Content $stdout -Raw -ErrorAction SilentlyContinue } else { '' }
        if ($p.ExitCode -ne 0) {
            $err = if (Test-Path $stderr) { Get-Content $stderr -Raw -ErrorAction SilentlyContinue } else { '' }
            throw "app.py $Command failed with exit code $($p.ExitCode). $err"
        }
        return ($out | ConvertFrom-Json)
    } finally { Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue }
}

function Invoke-PosterText([string]$Command) {
    $py = (Get-Command py.exe -ErrorAction Stop).Source
    $stdout = Join-Path $env:TEMP ('vm-admin-recover-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('vm-admin-recover-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $p = Start-Process -FilePath $py -ArgumentList @('-3.12','app.py',$Command) -WorkingDirectory $poster -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = ''
        if (Test-Path $stdout) { $out += (Get-Content $stdout -Raw -ErrorAction SilentlyContinue) }
        if (Test-Path $stderr) { $err = Get-Content $stderr -Raw -ErrorAction SilentlyContinue; if ($err) { $out += "`n" + $err } }
        if ($p.ExitCode -ne 0) { throw "app.py $Command failed with exit code $($p.ExitCode)." }
        return $out.Trim()
    } finally { Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue }
}

function Test-AdminBotApi([string]$Token) {
    try {
        $response = Invoke-RestMethod -Method Get -Uri ("https://api.telegram.org/bot{0}/getMe" -f $Token) -TimeoutSec 15
        return [bool]$response.ok
    } catch { return $false }
}

Write-Host '============================================================'
Write-Host ' VM ADMIN COMMAND CENTRE - PARTIAL CUTOVER RECOVERY'
Write-Host '============================================================'
Write-Host 'Mode: ADMIN-ONLY / FAIL-CLOSED'
Write-Host 'Poster restart: NOT PERFORMED'
Write-Host 'Campaign activation: NOT PERFORMED'
Write-Host ''

if (-not (Test-Path -LiteralPath $posterSettings -PathType Leaf)) { throw 'Poster settings.py missing.' }
if (-not (Test-Path -LiteralPath $adminEnv -PathType Leaf)) { throw 'Admin Command Centre .env missing.' }
if (-not (Test-Path -LiteralPath $adminMain -PathType Leaf)) { throw 'Admin Command Centre main.py missing.' }
if (-not [regex]::IsMatch((Get-Content -LiteralPath $posterSettings -Raw),'(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False')) { throw 'Embedded poster admin guard is not forced off.' }
$token = Read-EnvValue $adminEnv 'VM_ADMIN_BOT_TOKEN'
$ids = Read-EnvValue $adminEnv 'VM_ADMIN_USER_IDS'
$mutations = Read-EnvValue $adminEnv 'VM_ADMIN_ALLOW_MUTATIONS'
if ([string]::IsNullOrWhiteSpace($token)) { throw 'VM_ADMIN_BOT_TOKEN is missing.' }
if ([string]::IsNullOrWhiteSpace($ids)) { throw 'VM_ADMIN_USER_IDS is missing.' }
if (($mutations + '').ToLowerInvariant() -ne 'false') { throw 'VM_ADMIN_ALLOW_MUTATIONS must be false.' }
$capacity = Invoke-PosterJson 'queue-capacity'
if ([int]$capacity.active_total -ne 0) { throw "Poster active_total is $($capacity.active_total); refusing admin recovery." }
$health = Invoke-PosterText 'health'
if ($health -notmatch '\[READY\]') { throw 'Poster health is not READY.' }
if ($health -notmatch 'admin control bot\s+optional / not configured') { throw 'Poster does not report embedded admin unconfigured.' }
$rootsBefore = @(Get-AdminRoots)
if ($rootsBefore.Count -ne 0) { throw "Admin Command Centre is already running ($($rootsBefore.Count) root(s)); refusing duplicate start." }

Write-Host 'Poster health: READY'
Write-Host 'Embedded poster admin: NOT CONFIGURED'
Write-Host 'Poster active queue: 0'
Write-Host 'Admin roots before recovery: 0'
Write-Host ''

$py = (Get-Command py.exe -ErrorAction Stop).Source
$quotedMain = '"' + $adminMain + '"'
$p = Start-Process -FilePath $py -ArgumentList @('-3.12',$quotedMain) -WorkingDirectory $admin -PassThru
Write-Host "Admin Command Centre start requested via py.exe (launcher PID $($p.Id))."
Start-Sleep -Seconds 8
$rootsAfter = @(Get-AdminRoots)
if ($rootsAfter.Count -ne 1) { throw "Expected exactly one Admin Command Centre root after recovery; found $($rootsAfter.Count)." }
$apiOk = Test-AdminBotApi $token
Write-Host "Admin Command Centre root PID: $($rootsAfter[0].ProcessId)"
Write-Host "Telegram Bot API getMe: $($(if($apiOk){'OK'}else{'UNVERIFIED'}))"
Write-Host ''
Write-Host 'ADMIN COMMAND CENTRE RECOVERY: PASSED'
Write-Host 'Smart Auto Poster: LEFT RUNNING / NOT RESTARTED'
Write-Host 'Embedded poster admin: DISABLED / UNCONFIGURED'
Write-Host 'Admin mutations: DISABLED'
Write-Host 'Campaign activation: NOT PERFORMED'
Write-Host 'Poster active queue: 0'
Write-Host 'Admin Command Centre roots: 1'
Write-Host ''
Write-Host 'Copy this entire output back to ChatGPT. Secret values are never printed.'
