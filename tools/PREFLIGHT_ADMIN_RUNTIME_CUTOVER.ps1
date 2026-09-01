param(
    [string]$Root
)

$ErrorActionPreference = 'Stop'

if (-not $Root) {
    $Root = (git rev-parse --show-toplevel).Trim()
}
$Root = (Resolve-Path $Root).Path
$poster = Join-Path $Root 'bots\Smart_Auto_Poster_V2'
$admin = Join-Path $Root 'bots\Admin_Command_Centre'

function Safe-Role([string]$CommandLine) {
    if ($CommandLine -match 'Admin_Command_Centre') { return 'ADMIN_COMMAND_CENTRE' }
    if ($CommandLine -match 'Smart_Auto_Poster_V2|smart_autoposter') { return 'SMART_AUTO_POSTER' }
    return 'RELATED'
}

function Get-Descendants([int]$Pid, $All) {
    $found = New-Object System.Collections.Generic.List[object]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($Pid)
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        foreach ($child in @($All | Where-Object { $_.ParentProcessId -eq $parent })) {
            $found.Add($child)
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    return @($found)
}

function Invoke-PosterReadOnly([string[]]$Args) {
    $app = Join-Path $poster 'app.py'
    if (-not (Test-Path -LiteralPath $app -PathType Leaf)) {
        return [pscustomobject]@{ Ran=$false; ExitCode=$null; Output='app.py not found' }
    }
    $py = $null
    try { $py = (Get-Command py.exe -ErrorAction Stop).Source } catch {}
    if (-not $py) { return [pscustomobject]@{ Ran=$false; ExitCode=$null; Output='py.exe not found' } }
    $stdout = Join-Path $env:TEMP ('vm-poster-preflight-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('vm-poster-preflight-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $argList = @('-3.12', 'app.py') + $Args
        $p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $poster -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = ''
        if (Test-Path $stdout) { $out += (Get-Content $stdout -Raw -ErrorAction SilentlyContinue) }
        if (Test-Path $stderr) {
            $err = Get-Content $stderr -Raw -ErrorAction SilentlyContinue
            if ($err) { $out += "`n" + $err }
        }
        $out = ($out -replace '(?i)(bot\d{5,}:[A-Za-z0-9_-]{20,})','[REDACTED_BOT_TOKEN]')
        if ($out.Length -gt 5000) { $out = $out.Substring($out.Length - 5000) }
        return [pscustomobject]@{ Ran=$true; ExitCode=$p.ExitCode; Output=$out.Trim() }
    } catch {
        return [pscustomobject]@{ Ran=$false; ExitCode=$null; Output=$_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
}

Write-Host '============================================================'
Write-Host ' VM ADMIN RUNTIME CUTOVER PREFLIGHT'
Write-Host '============================================================'
Write-Host 'Mode: READ-ONLY / NO PROCESS OR FILE CHANGES'
Write-Host "Root: $Root"
Write-Host ''

Write-Host '[1/4] Relevant Windows process tree'
$all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$roots = @($all | Where-Object {
    $_.CommandLine -and
    $_.Name -match '^(python(w)?|py|powershell|pwsh)\.exe$' -and
    ($_.CommandLine -match 'Smart_Auto_Poster_V2|smart_autoposter|Admin_Command_Centre')
})
if ($roots.Count -eq 0) {
    Write-Host 'No directly matching process roots found.'
} else {
    $seen = @{}
    foreach ($r in $roots | Sort-Object ProcessId) {
        if ($seen.ContainsKey([int]$r.ProcessId)) { continue }
        $seen[[int]$r.ProcessId] = $true
        $role = Safe-Role $r.CommandLine
        Write-Host ("ROOT PID {0,-7} PPID {1,-7} {2,-22} {3}" -f $r.ProcessId,$r.ParentProcessId,$role,$r.Name)
        foreach ($d in Get-Descendants ([int]$r.ProcessId) $all) {
            if ($seen.ContainsKey([int]$d.ProcessId)) { continue }
            $seen[[int]$d.ProcessId] = $true
            $drole = Safe-Role ($d.CommandLine + '')
            Write-Host ("  CHILD PID {0,-7} PPID {1,-7} {2,-20} {3}" -f $d.ProcessId,$d.ParentProcessId,$drole,$d.Name)
        }
    }
}
Write-Host ''

Write-Host '[2/4] Existing launcher candidates'
$posterCandidates = @(
    'START.ps1','START.bat','START.cmd','RUN.ps1','RUN.bat','SERVICE.ps1',
    'START_SMART_AUTO_POSTER.ps1','START_SMART_AUTO_POSTER.bat',
    'RUN_SMART_AUTO_POSTER.ps1','RUN_SMART_AUTO_POSTER.bat'
)
$adminCandidates = @('START_ADMIN_COMMAND_CENTRE.bat','START.ps1','START.bat','RUN.ps1','RUN.bat')
$posterFound = @($posterCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $poster $_) })
$adminFound = @($adminCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $admin $_) })
Write-Host ('Poster launchers: ' + ($(if($posterFound){$posterFound -join ', '}else{'NONE OF COMMON NAMES'})))
Write-Host ('Admin launchers:  ' + ($(if($adminFound){$adminFound -join ', '}else{'NONE OF COMMON NAMES'})))
Write-Host ''

Write-Host '[3/4] Smart Auto Poster read-only status probes'
foreach ($probe in @(@('status'),@('health'),@('queue-capacity'))) {
    $name = $probe[0]
    Write-Host "--- app.py $name ---"
    $r = Invoke-PosterReadOnly $probe
    Write-Host "Ran: $($r.Ran) ExitCode: $($r.ExitCode)"
    if ($r.Output) { Write-Host $r.Output }
}
Write-Host ''

Write-Host '[4/4] Cutover readiness summary'
$posterSettings = Join-Path $poster 'smart_autoposter\settings.py'
$guarded = $false
if (Test-Path $posterSettings) {
    $text = Get-Content -LiteralPath $posterSettings -Raw
    $guarded = [regex]::IsMatch($text,'(?ms)def\s+admin_bot_enabled[\s\S]{0,500}?return\s+False')
}
$adminEnv = Join-Path $admin '.env'
$adminToken = $false
$adminIds = $false
if (Test-Path $adminEnv) {
    foreach($line in Get-Content $adminEnv){
        $t=$line.Trim()
        if($t -match '^VM_ADMIN_BOT_TOKEN\s*=\s*(.+)$' -and -not [string]::IsNullOrWhiteSpace($Matches[1])){$adminToken=$true}
        if($t -match '^VM_ADMIN_USER_IDS\s*=\s*(.+)$' -and -not [string]::IsNullOrWhiteSpace($Matches[1])){$adminIds=$true}
    }
}
Write-Host "Poster embedded admin disabled on disk: $guarded"
Write-Host "Admin Command Centre token present:       $adminToken"
Write-Host "Admin Command Centre admin IDs present:   $adminIds"
Write-Host ''
Write-Host 'No files, processes, queues, campaigns, sessions, or Git refs were modified.'
Write-Host 'Copy this entire output back to ChatGPT.'
