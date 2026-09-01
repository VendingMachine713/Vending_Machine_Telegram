param(
    [string]$ZipPath = ""
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Find-PythonRuntime {
    foreach ($candidate in @("py", "python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    return $null
}

if ([string]::IsNullOrWhiteSpace($ZipPath)) {
    $ZipPath = Get-ChildItem "$HOME\Downloads" -Filter "VM_Relationship_Manager_DIRECT_UPDATE_*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if ([string]::IsNullOrWhiteSpace($ZipPath) -or -not (Test-Path -LiteralPath $ZipPath)) {
    throw "No VM Relationship Manager direct-update ZIP was found."
}

$python = Find-PythonRuntime
if (-not $python) {
    throw "Python was not found. Update was not applied."
}

if (Test-Path ".\UPDATE_VM_RM_PREFLIGHT.py") {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $python -B ".\UPDATE_VM_RM_PREFLIGHT.py"
        $guardRc = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
    if ($guardRc -ne 0) {
        throw "Update blocked by runtime pre-flight. No files were changed."
    }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $entries = @($archive.Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) })
    $forbidden = @()
    foreach ($entry in $entries) {
        $name = $entry.FullName.Replace('/', '\')
        if ($name -match '(^|\\)\.\.(\\|$)' -or $name.StartsWith('\') -or $name -match '^[A-Za-z]:') {
            $forbidden += "unsafe-path:$name"
            continue
        }
        $leaf = [System.IO.Path]::GetFileName($name)
        if ($leaf -eq ".env" -or $leaf -like ".env.*" -or $name -like "runtime\*" -or $name -like "*\runtime\*" -or $name -like "*.session" -or $name -like "*.session-journal" -or $name -like "*.db" -or $name -like "*.db-wal" -or $name -like "*.db-shm" -or $name -like "*.sqlite" -or $name -like "*.sqlite3") {
            $forbidden += $name
        }
    }
    if ($forbidden.Count -gt 0) {
        throw "Update rejected: protected runtime/private files were found in the ZIP: $($forbidden -join ', ')"
    }
    $updateNames = @($entries | ForEach-Object { $_.FullName.Replace('/', '\') })
}
finally {
    $archive.Dispose()
}

$master = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$releaseBackupDir = Join-Path $master "shared\backups\VM_Relationship_Manager\code_releases"
New-Item -ItemType Directory -Force -Path $releaseBackupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$snapshotDir = Join-Path $env:TEMP "vm_rm_code_snapshot_$stamp"
$snapshotZip = Join-Path $releaseBackupDir "code_before_update_$stamp.zip"
New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null

$existingBefore = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $updateNames) {
    $target = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        [void]$existingBefore.Add($name)
        $dest = Join-Path $snapshotDir $name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath $target -Destination $dest -Force
    }
}

$manifest = [ordered]@{
    created_at = (Get-Date).ToString("o")
    update_zip = $ZipPath
    update_files = $updateNames
    existed_before = @($existingBefore)
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $snapshotDir "ROLLBACK_MANIFEST.json") -Encoding UTF8
Compress-Archive -Path (Join-Path $snapshotDir "*") -DestinationPath $snapshotZip -Force
Remove-Item -LiteralPath $snapshotDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[+] Code rollback snapshot:" $snapshotZip
Write-Host "[+] Protected runtime files checked: PASS"
Write-Host "[+] Applying:" $ZipPath

Expand-Archive -Path $ZipPath -DestinationPath $PSScriptRoot -Force

$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $python -B ".\smoke_test.py"
    $smokeRc = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldPreference
}

if ($smokeRc -ne 0) {
    Write-Host "[X] Smoke test failed. Rolling code files back automatically..."
    $rollbackTemp = Join-Path $env:TEMP "vm_rm_rollback_$stamp"
    New-Item -ItemType Directory -Force -Path $rollbackTemp | Out-Null
    Expand-Archive -Path $snapshotZip -DestinationPath $rollbackTemp -Force
    $savedManifest = Get-Content -LiteralPath (Join-Path $rollbackTemp "ROLLBACK_MANIFEST.json") -Raw | ConvertFrom-Json
    $beforeSet = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $savedManifest.existed_before) { [void]$beforeSet.Add([string]$name) }

    foreach ($name in $savedManifest.update_files) {
        $target = Join-Path $PSScriptRoot ([string]$name)
        if ($beforeSet.Contains([string]$name)) {
            $source = Join-Path $rollbackTemp ([string]$name)
            if (Test-Path -LiteralPath $source) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                Copy-Item -LiteralPath $source -Destination $target -Force
            }
        }
        else {
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $rollbackTemp -Recurse -Force -ErrorAction SilentlyContinue
    throw "Update smoke test failed and code rollback was applied. Runtime data was untouched."
}

Write-Host "[+] Update smoke test: PASS"
if (Test-Path ".\VERSION.txt") {
    Write-Host "[+] Installed version:"
    Get-Content ".\VERSION.txt"
}
Write-Host "[+] Update applied successfully. Runtime data, .env and Telegram sessions were not modified."
