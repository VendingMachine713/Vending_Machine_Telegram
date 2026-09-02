param(
    [ValidateSet('Rebuild','Search','Listing','PriceHistory','Stats')]
    [string]$Mode = 'Stats',
    [string]$Query = '',
    [long]$Chat = 0,
    [int]$Id = 0,
    [int]$Limit = 0
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Py([string[]]$PyArgs) {
    & py @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: py $($PyArgs -join ' ')"
    }
}

switch ($Mode) {
    'Rebuild' {
        $args = @('.\marketplace_cli.py', 'rebuild')
        if ($Limit -gt 0) { $args += @('--limit', [string]$Limit) }
        Invoke-Py $args
    }
    'Search' {
        $args = @('.\marketplace_cli.py', 'search')
        if ($Query) { $args += $Query }
        if ($Chat -ne 0) { $args += @('--chat', [string]$Chat) }
        Invoke-Py $args
    }
    'Listing' {
        if ($Id -le 0) { throw '-Id is required for Listing mode.' }
        Invoke-Py @('.\marketplace_cli.py', 'listing', [string]$Id)
    }
    'PriceHistory' {
        if ($Id -le 0) { throw '-Id is required for PriceHistory mode.' }
        Invoke-Py @('.\marketplace_cli.py', 'price-history', [string]$Id)
    }
    'Stats' {
        $args = @('.\marketplace_cli.py', 'stats')
        if ($Chat -ne 0) { $args += @('--chat', [string]$Chat) }
        Invoke-Py $args
    }
}
