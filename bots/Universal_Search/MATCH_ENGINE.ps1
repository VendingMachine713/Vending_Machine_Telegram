param(
    [ValidateSet('Bootstrap','Refresh','List','Show','Stats','Queue','Cleanup','RetryFailed','Notifications','Feedback')]
    [string]$Mode = 'Stats',
    [double]$MinScore = 45,
    [int]$Limit = 20,
    [int]$Id = 0,
    [long]$UserId = 0,
    [ValidateSet('status','on','off')]
    [string]$State = 'status',
    [ValidateSet('relevant','not_relevant','accepted','ignore')]
    [string]$Verdict = 'relevant',
    [string]$Note = ''
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
    'Queue' {
        & py .\match_cli.py queue
    }
    'Cleanup' {
        & py .\match_cli.py cleanup
    }
    'RetryFailed' {
        $args = @('.\match_cli.py', 'retry-failed', '--limit', [string]$Limit)
        if ($UserId -gt 0) { $args += @('--user-id', [string]$UserId) }
        & py @args
    }
    'Notifications' {
        & py .\match_cli.py notifications $State
    }
    'Feedback' {
        if ($Id -le 0) { throw 'Feedback mode requires -Id <match id>.' }
        $args = @('.\match_cli.py', 'feedback', [string]$Id, $Verdict)
        if ($UserId -gt 0) { $args += @('--user-id', [string]$UserId) }
        if ($Note) { $args += @('--note', $Note) }
        & py @args
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Match Engine command failed with exit code $LASTEXITCODE"
}
