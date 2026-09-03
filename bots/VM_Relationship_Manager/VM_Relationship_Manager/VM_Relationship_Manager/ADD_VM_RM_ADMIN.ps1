param(
    [Parameter(Mandatory=$false)]
    [string]$TelegramId
)

$ErrorActionPreference = "Stop"
$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvPath = Join-Path $BotDir ".env"

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Write-Host "[X] .env was not found at: $EnvPath" -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($TelegramId)) {
    $TelegramId = Read-Host "Enter the BACKUP account's numeric Telegram user ID"
}

$TelegramId = $TelegramId.Trim()

if ($TelegramId -notmatch '^\d{5,20}$') {
    Write-Host "[X] Telegram ID must be numeric only." -ForegroundColor Red
    exit 1
}

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content -LiteralPath $EnvPath | ForEach-Object { [void]$lines.Add($_) }

$adminIndex = -1
$currentIds = @()

for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*ADMIN_IDS\s*=(.*)$') {
        $adminIndex = $i
        $value = $Matches[1].Trim()
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $currentIds = @(
                $value.Split(',') |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -match '^\d+$' }
            )
        }
        break
    }
}

$allIds = @($currentIds + $TelegramId | Select-Object -Unique)

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $BotDir ".env.admin_backup_$timestamp"
Copy-Item -LiteralPath $EnvPath -Destination $backupPath -Force

$newLine = "ADMIN_IDS=" + ($allIds -join ",")

if ($adminIndex -ge 0) {
    $lines[$adminIndex] = $newLine
} else {
    [void]$lines.Add($newLine)
}

Set-Content -LiteralPath $EnvPath -Value $lines -Encoding UTF8

Write-Host ""
Write-Host "[+] Backup admin access added successfully." -ForegroundColor Green
Write-Host "[+] ADMIN_IDS now contains $($allIds.Count) authorised account(s)."
Write-Host "[+] A local .env backup was created before the change."
Write-Host "[!] Restart VM Relationship Manager for the change to take effect." -ForegroundColor Yellow
Write-Host ""
Write-Host "Do not share your .env file or bot token."
