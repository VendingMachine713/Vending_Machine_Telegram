$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Find-PythonRuntime {
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $candidate }
    }
    return $null
}

$script:PythonCommand = Find-PythonRuntime
$script:LastPythonExitCode = 0

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $script:PythonCommand @Args
        $script:LastPythonExitCode = $LASTEXITCODE
        if ($null -eq $script:LastPythonExitCode) {
            $script:LastPythonExitCode = 1
        }
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Invoke-PythonStdin {
    param([Parameter(Mandatory=$true)][string]$Code)

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Code | & $script:PythonCommand -
        $script:LastPythonExitCode = $LASTEXITCODE
        if ($null -eq $script:LastPythonExitCode) {
            $script:LastPythonExitCode = 1
        }
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
}

Write-Host "============================================================"
Write-Host " VM RELATIONSHIP MANAGER"
Write-Host "============================================================"

if (Test-Path ".\VERSION.txt") {
    Write-Host ""
    Get-Content ".\VERSION.txt"
}

Write-Host ""
Write-Host "[1/4] Checking Python runtime and required packages..."

if ([string]::IsNullOrWhiteSpace($script:PythonCommand)) {
    Write-Host "[X] No Python runtime command was found (checked: py, python, python3)."
    exit 10
}

Write-Host "[+] Python command: $script:PythonCommand"
Invoke-Python "--version"
if ($script:LastPythonExitCode -ne 0) {
    Write-Host "[X] Python runtime was found but could not be executed."
    exit 10
}

$dependencyProbe = @'
import importlib.util
import re
from importlib.metadata import PackageNotFoundError, version

mods = ["dotenv", "telethon", "telegram", "apscheduler"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
problems = []

if missing:
    problems.append("missing modules: " + ", ".join(missing))

def numeric(v):
    parts = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple(parts + [0] * (3-len(parts)))

checks = {
    "Telethon": ((1, 44, 0), (2, 0, 0)),
    "python-telegram-bot": ((22, 8, 0), (23, 0, 0)),
    "APScheduler": ((3, 10, 0), (4, 0, 0)),
}
for package, (minimum, maximum) in checks.items():
    try:
        current = numeric(version(package))
        if current < minimum or current >= maximum:
            problems.append(f"{package}={version(package)} outside supported range")
    except PackageNotFoundError:
        problems.append(f"{package} not installed")

if problems:
    print("[!] Python runtime repair required: " + "; ".join(problems))
    raise SystemExit(1)

print("[+] Required Python modules and supported versions detected.")
'@

Invoke-PythonStdin $dependencyProbe
$probeCode = $script:LastPythonExitCode

if ($probeCode -ne 0) {
    Write-Host "[!] Installing/repairing the VM Relationship Manager Python runtime set..."
    if (Test-Path ".\requirements.txt") {
        Invoke-Python "-m" "pip" "install" "--disable-pip-version-check" "-r" ".\requirements.txt"
    }
    else {
        Invoke-Python "-m" "pip" "install" "--disable-pip-version-check" `
            "python-dotenv>=1.0,<2" `
            "tzdata>=2026.3" `
            "telethon>=1.44,<2" `
            "python-telegram-bot>=22.8,<23" `
            "apscheduler>=3.10,<4"
    }

    if ($script:LastPythonExitCode -ne 0) {
        Write-Host "[X] Dependency installation failed."
        exit 11
    }
}

Write-Host "[+] Python runtime ready."

Write-Host ""
Write-Host "[2/4] Running configuration pre-flight..."

$preflight = @'
from pathlib import Path
from config import load_settings

s = load_settings()
session_file = Path(s.session_name)
if session_file.suffix != ".session":
    session_file = Path(str(session_file) + ".session")
if not s.phone and not session_file.exists():
    raise RuntimeError("No TELEGRAM_PHONE is configured and the saved Telethon session is missing")

print("[+] PRE-FLIGHT PASSED")
print(f"[+] Timezone: {s.timezone}")
print(f"[+] Admin IDs configured: {len(s.admin_ids)}")
print(f"[+] Session: {s.session_name} ({'present' if session_file.exists() else 'fresh login available'})")
print(f"[+] Database target: {s.database_path}")
print(f"[+] Backup target: {s.backup_dir}")
print(f"[+] Log target: {s.log_dir}")
print("[+] Telegram secrets detected without displaying them.")
'@

Invoke-PythonStdin $preflight
$preflightCode = $script:LastPythonExitCode

if ($preflightCode -ne 0) {
    Write-Host "[X] Configuration pre-flight failed. Bot was not started."
    exit 20
}

Write-Host "[+] Configuration pre-flight passed."

Write-Host ""
Write-Host "[3/4] Running relationship engine smoke test..."

if (-not (Test-Path ".\smoke_test.py")) {
    Write-Host "[X] smoke_test.py is missing. Bot was not started."
    exit 30
}

Invoke-Python ".\smoke_test.py"
if ($script:LastPythonExitCode -ne 0) {
    Write-Host "[X] Smoke test failed. Bot was not started."
    exit 31
}

Write-Host "[+] Smoke test passed."

Write-Host ""
Write-Host "[4/4] Starting VM Relationship Manager..."
Write-Host "Press Ctrl+C to stop it cleanly."
Write-Host ""

if (-not (Test-Path ".\main.py")) {
    Write-Host "[X] main.py is missing."
    exit 40
}

Invoke-Python ".\main.py"
exit $script:LastPythonExitCode
