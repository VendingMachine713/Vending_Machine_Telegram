param(
    [string]$Message = "",
    [switch]$NoPush
)

$ErrorActionPreference="Stop"
$Root="C:\Users\cherr\OneDrive\Desktop\Vending_Machine_Telegram"
Set-Location $Root

function Fail([string]$msg){
    Write-Host "[FAIL] $msg"
    exit 1
}

Write-Host "=== VM SAFE RELEASE ==="

Write-Host "[1/8] Backup..."
& cmd.exe /c "`"$Root\VM.cmd`" backup" | Out-Host
if($LASTEXITCODE -ne 0){ Fail "Backup failed." }

Write-Host "[2/8] Secret scan..."
$Guard=Join-Path $Root "tools\vm_core\git\git_guard.py"
if(Test-Path $Guard){
    & py $Guard
    if($LASTEXITCODE -ne 0){ Fail "Secret scan blocked release." }
}

Write-Host "[3/8] Platform tests..."
$testDirs=@(
    (Join-Path $Root "tests"),
    (Join-Path $Root "bots\Admin_Command_Centre\tests"),
    (Join-Path $Root "bots\Universal_Search\tests"),
    (Join-Path $Root "bots\VM_Guard\tests"),
    (Join-Path $Root "bots\Smart_Auto_Poster_V2\tests"),
    (Join-Path $Root "bots\VM_Relationship_Manager\tests")
)

$failed=$false
foreach($dir in $testDirs){
    if(Test-Path $dir){
        $parent=Split-Path -Parent $dir
        Push-Location $parent
        py -m unittest discover -s (Split-Path -Leaf $dir) -q
        if($LASTEXITCODE -ne 0){ $failed=$true }
        Pop-Location
    }
}
if($failed){ Fail "One or more tests failed. Nothing pushed." }

Write-Host "[4/8] Git checks..."
git add -A
if(Test-Path $Guard){
    & py $Guard --staged
    if($LASTEXITCODE -ne 0){
        git reset | Out-Null
        Fail "Staged secret scan blocked release."
    }
}
git diff --cached --check
if($LASTEXITCODE -ne 0){ Fail "Git content check failed." }

$changes=git diff --cached --name-only
if(!$changes){
    Write-Host "[OK] No code changes to release."
}else{
    Write-Host "[5/8] Commit..."
    if(!$Message){
        $Message="release: VM platform $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }
    & cmd.exe /c "git commit -m `"$Message`"" | Out-Host
    if($LASTEXITCODE -ne 0){ Fail "Git commit failed." }
}

Write-Host "[6/8] Push..."
if(!$NoPush){
    & cmd.exe /c "git push" | Out-Host
    if($LASTEXITCODE -ne 0){ Fail "Git push failed." }
    if($LASTEXITCODE -ne 0){ Fail "Git push failed." }
}else{
    Write-Host "[SKIP] Push disabled by -NoPush."
}

Write-Host "[7/8] Health recovery..."
& cmd.exe /c "`"$Root\VM.cmd`" restart-failed" | Out-Host
Start-Sleep 10

Write-Host "[8/8] Final status..."
& cmd.exe /c "`"$Root\VM.cmd`" status" | Out-Host

Write-Host ""
Write-Host "[PASS] VM safe release completed."

