$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$displayVersion = "unknown"
if (Test-Path "VERSION.txt") {
    $buildLine = Get-Content "VERSION.txt" | Where-Object { $_ -match "^Build:\s*(.+)$" } | Select-Object -First 1
    if ($buildLine -and $buildLine -match "^Build:\s*(.+)$") {
        $displayVersion = $Matches[1].Trim()
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VM RELATIONSHIP MANAGER  v$displayVersion" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".env")) {
    Write-Host "[!] .env does not exist." -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[+] Created .env from .env.example" -ForegroundColor Green
        Write-Host "[!] Fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, BOT_TOKEN and ADMIN_IDS." -ForegroundColor Yellow
        notepad ".env"
    }
    Read-Host "Press Enter after saving .env"
}

Write-Host "[1/4] Checking required Python packages..." -ForegroundColor Cyan

# Native Python commands can write to stderr when a dependency is missing.
# Temporarily prevent PowerShell from treating that expected stderr as a
# terminating PowerShell exception so we can inspect $LASTEXITCODE ourselves.
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

py -c "import telethon, telegram, dotenv; from zoneinfo import ZoneInfo; ZoneInfo('Australia/Adelaide')" *> $null
$dependencyCheckExitCode = $LASTEXITCODE

$ErrorActionPreference = $previousErrorActionPreference

if ($dependencyCheckExitCode -ne 0) {
    Write-Host "[!] A dependency or timezone package is missing. Installing/updating requirements..." -ForegroundColor Yellow

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    py -m pip install -r requirements.txt
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($installExitCode -ne 0) {
        Write-Host "[X] Requirements installation failed." -ForegroundColor Red
        exit $installExitCode
    }

    # Verify again after installation.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    py -c "import telethon, telegram, dotenv; from zoneinfo import ZoneInfo; ZoneInfo('Australia/Adelaide')" *> $null
    $verifyExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($verifyExitCode -ne 0) {
        Write-Host "[X] Dependencies installed, but Adelaide timezone support still failed." -ForegroundColor Red
        Write-Host "Run: py -m pip install --upgrade tzdata" -ForegroundColor Yellow
        exit $verifyExitCode
    }
}

Write-Host "[+] Requirements and Adelaide timezone data ready." -ForegroundColor Green

Write-Host "[2/4] Running configuration pre-flight..." -ForegroundColor Cyan
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
py preflight.py
$preflightExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($preflightExitCode -ne 0) {
    Write-Host ""
    Write-Host "[X] Pre-flight failed. Fix the item above, then run the launcher again." -ForegroundColor Red
    exit $preflightExitCode
}
Write-Host "[+] Configuration pre-flight passed." -ForegroundColor Green

Write-Host "[3/4] Running relationship engine smoke test..." -ForegroundColor Cyan
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
py smoke_test.py
$smokeExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($smokeExitCode -ne 0) {
    Write-Host "[X] Smoke test failed. Bot was not started." -ForegroundColor Red
    exit $smokeExitCode
}
Write-Host "[+] Smoke test passed." -ForegroundColor Green

Write-Host "[4/4] Starting VM Relationship Manager..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop it cleanly." -ForegroundColor DarkGray
Write-Host ""

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
py main.py
$botExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

exit $botExitCode
