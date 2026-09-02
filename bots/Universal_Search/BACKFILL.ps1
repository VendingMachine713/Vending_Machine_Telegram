param(
    [ValidateSet("Status","ListChats","Chat","All")]
    [string]$Mode = "Status",
    [string]$Chat,
    [int]$Limit = 5000,
    [int]$Days = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$ArgsList = @(".\backfill.py")

switch ($Mode) {
    "Status"    { $ArgsList += "--status" }
    "ListChats" { $ArgsList += "--list-chats" }
    "Chat" {
        if ([string]::IsNullOrWhiteSpace($Chat)) {
            throw "-Chat is required when -Mode Chat is used."
        }
        $ArgsList += @("--chat", $Chat)
    }
    "All"       { $ArgsList += "--all" }
}

if ($Mode -ne "Status" -and $Mode -ne "ListChats") {
    $ArgsList += @("--limit", [string]$Limit)
    if ($Days -gt 0) {
        $ArgsList += @("--days", [string]$Days)
    }
}

Write-Host "============================================================"
Write-Host " VM UNIVERSAL SEARCH - HISTORICAL BACKFILL V1.1"
Write-Host "============================================================"
Write-Host "Mode       : $Mode"
Write-Host "Read only  : TRUE (Telegram history is never modified)"
Write-Host "Media      : metadata only; files are not downloaded"
Write-Host ""

& py @ArgsList
if ($LASTEXITCODE -ne 0) {
    throw "Universal Search backfill exited with code $LASTEXITCODE."
}
