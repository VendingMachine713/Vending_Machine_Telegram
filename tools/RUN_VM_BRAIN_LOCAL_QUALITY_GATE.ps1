param(
    [switch]$IncludeBotCore
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-GateStep {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][scriptblock]$Command
    )
    Write-Host ""
    Write-Host ("=== {0} ===" -f $Name)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw ("Quality gate failed: {0} (exit {1})" -f $Name, $LASTEXITCODE)
    }
}

Write-Host "============================================================"
Write-Host " VM BRAIN LOCAL QUALITY GATE"
Write-Host "============================================================"
Write-Host ("Repository : {0}" -f $Root)
Write-Host ("Branch     : {0}" -f ((git branch --show-current) 2>$null))
Write-Host ("Commit     : {0}" -f ((git rev-parse --short HEAD) 2>$null))
Write-Host ("Python     : {0}" -f ((python --version) 2>&1))
Write-Host ""
Write-Host "This gate performs validation only. It does not activate VM Brain rules,"
Write-Host "send Telegram messages, retry Smart Auto Poster jobs, or modify bot data."

Invoke-GateStep "Compile VM platform" {
    python -m compileall -q shared tests tools vm.py
}

Invoke-GateStep "VM platform tests" {
    python -m unittest discover -s tests -p "test_*.py" -v
}

if ($IncludeBotCore) {
    foreach ($Bot in @('Universal_Search', 'VM_Guard', 'Admin_Command_Centre')) {
        Invoke-GateStep ("Bot tests: {0}" -f $Bot) {
            Push-Location (Join-Path $Root "bots/$Bot")
            try {
                python -m compileall -q .
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
                python -m unittest discover -s tests -p "test_*.py" -v
            }
            finally {
                Pop-Location
            }
        }
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host " VM BRAIN LOCAL QUALITY GATE: PASS"
Write-Host "============================================================"
Write-Host "Safe to use this result as an additional local validation signal."
Write-Host "Do not treat it as a substitute for GitHub CI once hosted runners recover."
