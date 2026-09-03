$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Active .env file is missing: $envPath"
}

function Read-EnvMap {
    param([Parameter(Mandatory=$true)][string]$Path)

    $map = [ordered]@{}
    $raw = [System.IO.File]::ReadAllText($Path)
    $raw = $raw.TrimStart([char]0xFEFF)

    foreach ($line in ($raw -split "`r?`n")) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        if ($trimmed.StartsWith("#")) { continue }

        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { continue }

        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()

        if (-not [string]::IsNullOrWhiteSpace($key)) {
            $map[$key] = $value
        }
    }

    return $map
}

function Write-EnvMap {
    param(
        [Parameter(Mandatory=$true)]$Map,
        [Parameter(Mandatory=$true)][string]$Path
    )

    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($key in $Map.Keys) {
        $lines.Add("$key=$($Map[$key])")
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $lines, $utf8NoBom)
}

$required = @(
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "BOT_TOKEN",
    "ADMIN_IDS"
)

$optionalImportant = @(
    "SESSION_NAME"
)

$current = Read-EnvMap -Path $envPath

$backupPath = Join-Path $PSScriptRoot (".env.before_auto_repair_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
Copy-Item -LiteralPath $envPath -Destination $backupPath -Force

Write-Host "============================================================"
Write-Host " VM RELATIONSHIP MANAGER - ENV RECOVERY"
Write-Host "============================================================"
Write-Host "[+] Safety backup created."
Write-Host "[+] No credential values will be displayed."

$missing = @()
foreach ($key in $required) {
    if (-not $current.Contains($key) -or [string]::IsNullOrWhiteSpace([string]$current[$key])) {
        $missing += $key
    }
}

if ($missing.Count -eq 0) {
    Write-Host "[+] All required keys already exist in the active .env."
}
else {
    Write-Host "[!] Missing required keys:" ($missing -join ", ")
}

# Search local timestamped env backups, newest first.
$candidates = Get-ChildItem -LiteralPath $PSScriptRoot -Force -File |
    Where-Object {
        $_.Name -like ".env*" -and
        $_.FullName -ne $envPath -and
        $_.FullName -ne $backupPath
    } |
    Sort-Object LastWriteTime -Descending

$restored = New-Object System.Collections.Generic.List[string]

foreach ($key in @($missing)) {
    foreach ($candidate in $candidates) {
        try {
            $candidateMap = Read-EnvMap -Path $candidate.FullName
        }
        catch {
            continue
        }

        if ($candidateMap.Contains($key) -and -not [string]::IsNullOrWhiteSpace([string]$candidateMap[$key])) {
            $current[$key] = $candidateMap[$key]
            $restored.Add($key)
            Write-Host "[+] Restored key:" $key "from local backup" $candidate.Name
            break
        }
    }
}

# Preserve/restore SESSION_NAME if it is absent. Prefer backup session.
if (-not $current.Contains("SESSION_NAME") -or [string]::IsNullOrWhiteSpace([string]$current["SESSION_NAME"])) {
    $restoredSession = $false

    foreach ($candidate in $candidates) {
        try {
            $candidateMap = Read-EnvMap -Path $candidate.FullName
        }
        catch {
            continue
        }

        if ($candidateMap.Contains("SESSION_NAME") -and -not [string]::IsNullOrWhiteSpace([string]$candidateMap["SESSION_NAME"])) {
            $current["SESSION_NAME"] = $candidateMap["SESSION_NAME"]
            $restoredSession = $true
            Write-Host "[+] Restored key: SESSION_NAME from local backup" $candidate.Name
            break
        }
    }

    if (-not $restoredSession) {
        $current["SESSION_NAME"] = "runtime/vm_relationship_backup"
        Write-Host "[+] SESSION_NAME was absent; set to existing verified backup-session path."
    }
}

$stillMissing = @()
foreach ($key in $required) {
    if (-not $current.Contains($key) -or [string]::IsNullOrWhiteSpace([string]$current[$key])) {
        $stillMissing += $key
    }
}

if ($stillMissing.Count -gt 0) {
    Write-Host ""
    Write-Host "[X] Could not recover these keys from local .env backups:" ($stillMissing -join ", ")
    Write-Host "[X] Active .env was NOT rewritten."
    exit 20
}

Write-EnvMap -Map $current -Path $envPath

Write-Host ""
Write-Host "[+] Active .env repaired."
Write-Host "[+] Required keys now present:" ($required -join ", ")
Write-Host "[+] Credential values were not displayed."

# Validate using the same Python runtime discovery order as the launcher.
$python = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $python = $candidate
        break
    }
}

if ([string]::IsNullOrWhiteSpace($python)) {
    Write-Host "[X] Could not find Python for validation."
    exit 30
}

$validation = @'
from config import load_settings
s = load_settings()
print("[+] CONFIG VALIDATION PASSED")
print("[+] Admin IDs configured:", len(s.admin_ids))
print("[+] Session:", s.session_name)
print("[+] Required Telegram credentials loaded without displaying them.")
'@

$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $validation | & $python -
    $rc = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldPreference
}

if ($rc -ne 0) {
    Write-Host "[X] Config validation still failed after repair."
    exit 40
}

Write-Host ""
Write-Host "[+] ENV RECOVERY COMPLETE"
Write-Host "[+] You can now run .\START_VM_RELATIONSHIPS.bat"
exit 0
