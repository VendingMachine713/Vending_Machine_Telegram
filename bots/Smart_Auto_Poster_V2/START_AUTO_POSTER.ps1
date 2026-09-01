$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
& (Join-Path $Root 'CONTROL_PANEL.ps1')
