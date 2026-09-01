$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Out=Join-Path $env:USERPROFILE "Downloads\VM_INTELLIGENCE_V3_VALIDATION_BUNDLE.zip"
$Stage=Join-Path $env:TEMP ("vm_intel_v3_validation_"+[guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Stage|Out-Null
try{
 foreach($rel in @(
  "diagnostics\intelligence_report.json",
  "diagnostics\intelligence_report.txt",
  "diagnostics\intelligence_brief.txt",
  "diagnostics\intelligence_attention.json",
  "diagnostics\intelligence_weekly.txt",
  "diagnostics\live_runtime.json",
  "diagnostics\full_validation.json",
  "logs\vm_intelligence_agent.log"
 )){
   $src=Join-Path $Root $rel
   if(Test-Path $src -PathType Leaf){
    $dst=Join-Path $Stage $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
    Copy-Item $src $dst -Force
   }
 }
 if(Test-Path $Out){Remove-Item $Out -Force}
 Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Out -Force
 Write-Host "[OK] Validation bundle: $Out"
}finally{
 Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
