$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'python'
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py' }
& $Python (Join-Path $Root 'tools\CONFIGURE_CENTRAL_OWNER.py')
exit $LASTEXITCODE
