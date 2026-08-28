$ErrorActionPreference="Stop"
$Root="C:\Users\cherr\OneDrive\Desktop\Vending_Machine_Telegram"
$Guard=Join-Path $Root "tools\vm_core\git\git_guard.py"
$Block=Join-Path $Root "tools\vm_core\git\gitignore_block.txt"
$Ignore=Join-Path $Root ".gitignore"

Set-Location $Root
if (!(Test-Path ".git")) {
    git init | Out-Host
}
git branch -M main 2>$null

$blockText=Get-Content $Block -Raw
$existing=if(Test-Path $Ignore){Get-Content $Ignore -Raw}else{""}
if($existing -notmatch "VM PLATFORM SECURITY / RUNTIME"){
    Add-Content $Ignore "`r`n$blockText"
}

$hooks=Join-Path $Root ".git\hooks"
Copy-Item (Join-Path $Root "tools\vm_core\git\pre-commit") (Join-Path $hooks "pre-commit") -Force
Copy-Item (Join-Path $Root "tools\vm_core\git\pre-push") (Join-Path $hooks "pre-push") -Force

Write-Host "[SECURITY] Scanning everything Git could track..."
& py $Guard
if($LASTEXITCODE -ne 0){
    Write-Host "[BLOCKED] Git baseline was NOT committed. Fix listed files first."
    exit 2
}

git add -A
& py $Guard --staged
if($LASTEXITCODE -ne 0){
    git reset | Out-Null
    Write-Host "[BLOCKED] Staged files failed secret scan. Nothing committed."
    exit 2
}
git diff --cached --check
if($LASTEXITCODE -ne 0){
    Write-Host "[BLOCKED] Git whitespace/content check failed."
    exit 3
}

$hasChanges = git diff --cached --name-only
if($hasChanges){
    $name = git config user.name
    $email = git config user.email
    if(!$name){ git config user.name "VM Automation" }
    if(!$email){ git config user.email "vm-automation@users.noreply.github.com" }
    git commit -m "chore: establish secure VM platform baseline" | Out-Host
} else {
    Write-Host "[OK] No uncommitted trackable changes."
}

Write-Host "[PASS] Secure local Git baseline ready."
git status --short
