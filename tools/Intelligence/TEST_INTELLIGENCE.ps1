$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$env:PYTHONPATH = "$Root;$env:PYTHONPATH"
py -m unittest discover -s tests/vm_intelligence -p "test_*.py" -v
exit $LASTEXITCODE
