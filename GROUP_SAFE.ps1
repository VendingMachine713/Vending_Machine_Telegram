$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'python'
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py' }
& $Python (Join-Path $Root 'tools\GROUP_SAFE.py')
exit $LASTEXITCODE
