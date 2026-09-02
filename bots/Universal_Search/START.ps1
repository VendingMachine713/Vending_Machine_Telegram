$ErrorActionPreference="Stop"
$Here=Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path (Join-Path $Here ".vm_disabled")) {
    Write-Host "[DISABLED] Configuration required."
    exit 0
}
$Venv=Join-Path $Here ".venv"
if (!(Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    py -m venv $Venv
    & (Join-Path $Venv "Scripts\python.exe") -m pip install --disable-pip-version-check -q -r (Join-Path $Here "requirements.txt")
}
& (Join-Path $Venv "Scripts\python.exe") (Join-Path $Here "main.py")
