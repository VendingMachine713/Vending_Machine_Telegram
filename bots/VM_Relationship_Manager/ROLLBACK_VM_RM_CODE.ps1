param(
    [string]$SnapshotZip = ""
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$master = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$releaseBackupDir = Join-Path $master "shared\backups\VM_Relationship_Manager\code_releases"

if ([string]::IsNullOrWhiteSpace($SnapshotZip)) {
    $SnapshotZip = Get-ChildItem $releaseBackupDir -Filter "code_before_update_*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if ([string]::IsNullOrWhiteSpace($SnapshotZip) -or -not (Test-Path -LiteralPath $SnapshotZip)) {
    throw "No code rollback snapshot found."
}

$temp = Join-Path $env:TEMP ("vm_rm_manual_rollback_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
Expand-Archive -Path $SnapshotZip -DestinationPath $temp -Force
$manifestPath = Join-Path $temp "ROLLBACK_MANIFEST.json"
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Rollback manifest is missing." }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$beforeSet = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $manifest.existed_before) { [void]$beforeSet.Add([string]$name) }

foreach ($name in $manifest.update_files) {
    $target = Join-Path $PSScriptRoot ([string]$name)
    if ($beforeSet.Contains([string]$name)) {
        $source = Join-Path $temp ([string]$name)
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $target -Force }
    }
    else {
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "[+] Code rollback applied from:" $SnapshotZip
Write-Host "[+] .env, runtime sessions, databases and shared data were untouched."
