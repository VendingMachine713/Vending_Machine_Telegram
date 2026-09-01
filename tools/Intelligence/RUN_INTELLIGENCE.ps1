param(
    [ValidateSet("ingest","report","status","brain","cycle")]
    [string]$Action = "report",
    [int]$Hours = 24
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$Python = $null
foreach ($candidate in @("py","python","python3")) {
    try {
        & $candidate -c "import sys; print(sys.executable)" *> $null
        if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
    } catch {}
}
if (-not $Python) { throw "Python was not found." }

$env:PYTHONPATH = "$Root;$env:PYTHONPATH"
if ($Action -eq "report") {
    & $Python -m shared.vm_intelligence.cli --root "$Root" ingest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m shared.vm_intelligence.cli --root "$Root" report --hours $Hours
} elseif ($Action -eq "ingest") {
    & $Python -m shared.vm_intelligence.cli --root "$Root" ingest
} elseif ($Action -eq "cycle") {
    & $Python -m shared.vm_intelligence.cli --root "$Root" cycle
} elseif ($Action -eq "brain") {
    & $Python -m shared.vm_intelligence.cli --root "$Root" brain
} else {
    & $Python -m shared.vm_intelligence.cli --root "$Root" status
}
exit $LASTEXITCODE
