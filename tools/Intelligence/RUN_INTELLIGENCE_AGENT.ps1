param([int]$IntervalSeconds=60)
$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$env:PYTHONPATH="$Root;$env:PYTHONPATH"
py -m shared.vm_intelligence.cli --root "$Root" agent --interval $IntervalSeconds
exit $LASTEXITCODE
