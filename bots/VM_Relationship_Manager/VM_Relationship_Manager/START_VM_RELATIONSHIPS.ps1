
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VM RELATIONSHIP MANAGER  v1.0.2" -ForegroundColor Cyan
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
py -c "import telethon, telegram, dotenv, tzdata; from zoneinfo import ZoneInfo; ZoneInfo('Australia/Adelaide')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] A dependency is missing. Installing/updating requirements..." -ForegroundColor Yellow
    py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Requirements installation failed." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
Write-Host "[+] Requirements and Adelaide timezone data ready." -ForegroundColor Green

Write-Host "[2/4] Running configuration pre-flight..." -ForegroundColor Cyan
py preflight.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[X] Pre-flight failed. Fix the item above, then run the launcher again." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[+] Configuration pre-flight passed." -ForegroundColor Green

Write-Host "[3/4] Running relationship engine smoke test..." -ForegroundColor Cyan
py smoke_test.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] Smoke test failed. Bot was not started." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[+] Smoke test passed." -ForegroundColor Green

Write-Host "[4/4] Starting VM Relationship Manager..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop it cleanly." -ForegroundColor DarkGray
Write-Host ""
py main.py
