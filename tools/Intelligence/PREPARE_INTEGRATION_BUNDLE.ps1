$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Downloads=Join-Path $env:USERPROFILE "Downloads"
$Stage=Join-Path $env:TEMP ("vm_intel_integration_"+[guid]::NewGuid().ToString("N"))
$Out=Join-Path $Downloads "VM_INTELLIGENCE_INTEGRATION_BUNDLE.zip"
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

function Write-SanitizedText([string]$Source,[string]$Destination) {
    $text=Get-Content -LiteralPath $Source -Raw -ErrorAction Stop
    # Redact common credential assignments while preserving surrounding code structure.
    # Environment/assignment form: preserve syntax and comments.
    $text=[regex]::Replace(
      $text,
      '(?im)^(\s*[A-Za-z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_HASH|SESSION_STRING)[A-Za-z0-9_]*\s*=\s*).*$',
      '$1"<REDACTED>"'
    )
    # Mapping/dictionary form: always retain a trailing comma; it is valid Python even
    # for the last item and prevents redaction from corrupting the surrounding mapping.
    $text=[regex]::Replace(
      $text,
      '(?im)^(\s*["'']?[A-Za-z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_HASH|SESSION_STRING)[A-Za-z0-9_]*["'']?\s*:\s*).*$',
      '$1"<REDACTED>",'
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination -Parent) | Out-Null
    [System.IO.File]::WriteAllText($Destination,$text,[System.Text.Encoding]::UTF8)
}

try {
    $allowedNames=@("BOT_MANIFEST.json","requirements.txt","pyproject.toml","setup.cfg","pytest.ini")
    $allowedExt=@(".py",".ps1",".bat",".cmd",".md",".toml")
    $skipParts=@("venv",".venv","__pycache__","backups","archive","data","logs","sessions","state",".git","node_modules")

    foreach($bot in Get-ChildItem -LiteralPath (Join-Path $Root "bots") -Directory) {
        foreach($f in Get-ChildItem -LiteralPath $bot.FullName -File -Recurse -ErrorAction SilentlyContinue) {
            $rel=$f.FullName.Substring($Root.Path.Length).TrimStart('\')
            $parts=$rel -split '[\\/]'
            if($parts | Where-Object {$skipParts -contains $_.ToLower()}){continue}
            if(($allowedNames -contains $f.Name) -or ($allowedExt -contains $f.Extension.ToLower())) {
                $dest=Join-Path $Stage $rel
                Write-SanitizedText $f.FullName $dest
            }
        }
    }

    foreach($rel in @(
      "diagnostics\intelligence_report.json",
      "diagnostics\intelligence_report.txt",
      "diagnostics\intelligence_brief.txt",
      "diagnostics\intelligence_attention.json",
      "diagnostics\live_runtime.json",
      "diagnostics\full_validation.json",
      "diagnostics\project_structure.txt",
      "state\vm_inventory.json"
    )){
        $src=Join-Path $Root $rel
        if(Test-Path -LiteralPath $src -PathType Leaf){
            $dest=Join-Path $Stage $rel
            Write-SanitizedText $src $dest
        }
    }

    $notice=@"
VM INTELLIGENCE INTEGRATION BUNDLE
Generated: $(Get-Date -Format o)

Purpose:
Architecture and integration review for VM Intelligence.

Excluded by design:
.env files, session files, databases, logs, backups, data directories, state databases,
Git internals, virtual environments, and other binary/runtime artifacts.

Common credential assignment lines are redacted automatically.
"@
    Set-Content -LiteralPath (Join-Path $Stage "BUNDLE_NOTICE.txt") -Value $notice -Encoding UTF8

    if(Test-Path -LiteralPath $Out){Remove-Item -LiteralPath $Out -Force}
    Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Out -Force
    Write-Host "[OK] Created integration bundle:" -ForegroundColor Green
    Write-Host "     $Out" -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
