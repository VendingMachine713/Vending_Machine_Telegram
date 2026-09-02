$ErrorActionPreference="Stop"
$Here=Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile=Join-Path $Here ".env"
if(!(Test-Path $EnvFile)){ exit 0 }
$Venv=Join-Path $Here ".venv"
if(!(Test-Path (Join-Path $Venv "Scripts\python.exe"))){ py -m venv $Venv }
$Py=Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --disable-pip-version-check -q -r (Join-Path $Here "requirements.txt")
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& $Py (Join-Path $Here "ops_bot.py")
