param(
    [Parameter(Mandatory=$false)]
    [string]$BackupPhone,

    [Parameter(Mandatory=$false)]
    [string]$BackupAdminId
)

$ErrorActionPreference = "Stop"
$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvPath = Join-Path $BotDir ".env"
$RuntimeDir = Join-Path $BotDir "runtime"

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Write-Host "[X] .env was not found at: $EnvPath" -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($BackupPhone)) {
    $BackupPhone = Read-Host "Enter the BACKUP Telegram account phone number (international format, e.g. +61...)"
}

$BackupPhone = $BackupPhone.Trim()
if ($BackupPhone -notmatch '^\+[1-9]\d{6,15}$') {
    Write-Host "[X] Phone must be in international format such as +61412345678." -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($BackupAdminId)) {
    $BackupAdminId = Read-Host "Enter the BACKUP account numeric Telegram user ID (or press Enter to leave ADMIN_IDS unchanged)"
}

$BackupAdminId = $BackupAdminId.Trim()
if ($BackupAdminId -and $BackupAdminId -notmatch '^\d{5,20}$') {
    Write-Host "[X] Telegram admin ID must be numeric only." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$envBackup = Join-Path $BotDir ".env.before_backup_switch_$timestamp"
Copy-Item -LiteralPath $EnvPath -Destination $envBackup -Force

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content -LiteralPath $EnvPath | ForEach-Object { [void]$lines.Add($_) }

function Set-EnvLine {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Name,
        [string]$Value
    )

    $found = $false
    for ($i = 0; $i -lt $List.Count; $i++) {
        if ($List[$i] -match ("^\s*" + [regex]::Escape($Name) + "\s*=")) {
            $List[$i] = "$Name=$Value"
            $found = $true
            break
        }
    }

    if (-not $found) {
        [void]$List.Add("$Name=$Value")
    }
}

Set-EnvLine -List $lines -Name "TELEGRAM_PHONE" -Value $BackupPhone

# Use a different Telethon session so the existing main-account session remains intact.
$backupSession = "runtime/vm_relationship_backup"
Set-EnvLine -List $lines -Name "SESSION_NAME" -Value $backupSession

if ($BackupAdminId) {
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

    $allIds = @($currentIds + $BackupAdminId | Select-Object -Unique)
    $adminLine = "ADMIN_IDS=" + ($allIds -join ",")

    if ($adminIndex -ge 0) {
        $lines[$adminIndex] = $adminLine
    } else {
        [void]$lines.Add($adminLine)
    }
}

Set-Content -LiteralPath $EnvPath -Value $lines -Encoding UTF8

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VM RELATIONSHIP MANAGER - BACKUP ACCOUNT SWITCH READY" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[+] Main Telethon session was NOT deleted or overwritten." -ForegroundColor Green
Write-Host "[+] Backup monitoring session: runtime\vm_relationship_backup.session" -ForegroundColor Green
Write-Host "[+] Current .env was backed up locally before changes." -ForegroundColor Green
if ($BackupAdminId) {
    Write-Host "[+] Backup Telegram admin ID was added while preserving existing admins." -ForegroundColor Green
}
Write-Host ""
Write-Host "NEXT:" -ForegroundColor Yellow
Write-Host "1. Start: .\START_VM_RELATIONSHIPS.bat"
Write-Host "2. When Telegram asks for a login code, use the code sent to the BACKUP account."
Write-Host "3. If Telegram asks for 2FA, enter the BACKUP account's 2FA password."
Write-Host "4. Open @VMRelationshipManagerBot from the backup account and send /rm."
Write-Host ""
Write-Host "Do not paste login codes, 2FA passwords, bot tokens, or API hashes into ChatGPT."
