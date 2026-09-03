param(
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root

$Python = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $Python = $candidate
        break
    }
}

if (-not $Python) {
    Write-Error 'Python was not found on PATH. Install/configure Python once, then rerun this script.'
}

$argsList = @('-m', 'shared.vm_core.recovery_cli')
if ($Json) { $argsList += '--json' }

Write-Host '============================================================'
Write-Host ' VM RECOVERY INTELLIGENCE - READ ONLY'
Write-Host '============================================================'
& $Python @argsList
exit $LASTEXITCODE
