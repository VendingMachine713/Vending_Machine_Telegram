param(
    [ValidateSet('Bootstrap','Refresh','List','Show','Stats','Notifications')]
    [string]$Mode = 'Stats',
    [double]$MinScore = 45,
    [int]$Limit = 20,
    [int]$Id = 0,
    [ValidateSet('status','on','off')]
    [string]$State = 'status'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher (py) was not found.'
}

switch ($Mode) {
    'Bootstrap' {
        & py .\match_cli.py bootstrap --min-score $MinScore
    }
    'Refresh' {
        & py .\match_cli.py refresh --min-score $MinScore
    }
    'List' {
        & py .\match_cli.py list --min-score $MinScore --limit $Limit
    }
    'Show' {
        if ($Id -le 0) { throw 'Show mode requires -Id <match id>.' }
        & py .\match_cli.py show $Id
    }
    'Stats' {
        & py .\match_cli.py stats
    }
    'Notifications' {
        & py .\match_cli.py notifications $State
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Match Engine command failed with exit code $LASTEXITCODE"
}
