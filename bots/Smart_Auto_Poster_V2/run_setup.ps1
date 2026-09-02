$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

Write-Host 'Smart Auto Poster V2.4 - setup / upgrade' -ForegroundColor Cyan

@(
 'config','data','data\cache','runtime','runtime\sessions','exports','backups','logs','diagnostics','updates',
 'updates\inbox','updates\applied','updates\failed','updates\backups',
 'content','content\inbox','content\library','content\archive','content\rejected'
) | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $Root $_) | Out-Null }

py -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }

if (-not (Test-Path .\.env)) {
    Copy-Item .\.env.example .\.env
    Write-Host 'Created .env. Add TELEGRAM_API_ID and TELEGRAM_API_HASH locally.' -ForegroundColor Yellow
}

# Never overwrite working local runtime files. Migrate only absent legacy files.
$legacyFiles = @(
    @{ Source='my_account.session'; Destination='runtime\sessions\my_account.session' },
    @{ Source='Auto_Post_Secondary.session'; Destination='runtime\sessions\Auto_Post_Secondary.session' },
    @{ Source='telegram_recommended_config.csv'; Destination='config\telegram_recommended_config.csv' },
    @{ Source='smart_autoposter.sqlite3'; Destination='data\smart_autoposter.sqlite3' },
    @{ Source='telegram_media_cache_v2_primary.json'; Destination='data\cache\telegram_media_cache_v2_primary.json' },
    @{ Source='telegram_media_cache_v2_secondary.json'; Destination='data\cache\telegram_media_cache_v2_secondary.json' }
)
foreach ($item in $legacyFiles) {
    $src = Join-Path $Root $item.Source; $dst = Join-Path $Root $item.Destination
    if ((Test-Path $src) -and (-not (Test-Path $dst))) { Copy-Item $src $dst; Write-Host "Copied legacy file -> $($item.Destination)" -ForegroundColor DarkCyan }
}

# Database backup before additive V2.4 migration if a DB already exists.
if (Test-Path .\data\smart_autoposter.sqlite3) {
    try { py .\app.py backup } catch { Write-Host "[WARNING] Pre-upgrade backup command failed: $($_.Exception.Message)" -ForegroundColor Yellow }
}

py .\app.py init
if ($LASTEXITCODE -ne 0) { throw 'Database migration/init failed' }
py -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw 'Python compile check failed' }
py -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Self-tests failed' }
py .\app.py integrity
if ($LASTEXITCODE -ne 0) { throw 'Database integrity check failed' }
py .\app.py health

# Safe one-time install/update of the master-folder patcher/rollback scripts.
if (Test-Path .\INSTALL_MASTER_UPDATER.ps1) {
    try { & .\INSTALL_MASTER_UPDATER.ps1 } catch { Write-Host "[WARNING] Master updater install skipped: $($_.Exception.Message)" -ForegroundColor Yellow }
}
Write-Host ''
Write-Host 'Setup complete. Open CONTROL_PANEL.ps1 to operate Smart Auto Poster V2.4.' -ForegroundColor Green
