param(
    [switch]$Once,
    [switch]$Observe,
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
    Write-Error 'Python was not found on PATH.'
}

$argsList = @('-m', 'shared.vm_core.autopilot_cli')
if ($Once) { $argsList += '--once' }
if ($Observe) { $argsList += '--observe' }
if ($Json) { $argsList += '--json' }

Write-Host '============================================================'
Write-Host ' VM RECOVERY AUTOPILOT'
Write-Host ' Central policy: config\vm_recovery_policy.json'
Write-Host ' Safe default: observe-only unless enabled + apply_safe are true'
Write-Host '============================================================'
& $Python @argsList
exit $LASTEXITCODE
