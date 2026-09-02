$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vm = Join-Path $Root "VM.ps1"
$LogDir = Join-Path $Root "shared\logs\VM_Core"
$Log = Join-Path $LogDir "watchdog.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "VMPlatformWatchdog_Stefan", [ref]$createdNew)
if (!$createdNew) { exit 0 }

try {
    Add-Content $Log "$(Get-Date -Format s) watchdog started"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Vm start | Out-Null
    while ($true) {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Vm restart-failed 2>&1
        if ($out) { $out | ForEach-Object { Add-Content $Log "$_" } }
        Start-Sleep -Seconds 60
    }
}
finally {
    try { $mutex.ReleaseMutex() } catch {}
    $mutex.Dispose()
}
