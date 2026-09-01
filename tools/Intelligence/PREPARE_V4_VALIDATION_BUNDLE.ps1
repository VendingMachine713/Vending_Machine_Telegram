$ErrorActionPreference="Stop"
$Root=Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Out=Join-Path $env:USERPROFILE "Downloads\VM_INTELLIGENCE_V5_VALIDATION_BUNDLE.zip"
$Stage=Join-Path $env:TEMP ("vm_intel_v5_validation_"+[guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Stage|Out-Null
try{
 foreach($rel in @(
  "diagnostics\intelligence_report.json",
  "diagnostics\intelligence_report.txt",
  "diagnostics\intelligence_brief.txt",
  "diagnostics\intelligence_attention.json",
  "diagnostics\intelligence_weekly.txt",
  "diagnostics\intelligence_runtime_registry.json",
  "diagnostics\intelligence_platform_service_registry.json",
  "diagnostics\intelligence_config_registry.json",
  "diagnostics\intelligence_platform_drift.json",
  "diagnostics\intelligence_platform_normalization.json",
  "diagnostics\intelligence_reliability.json",
  "diagnostics\intelligence_objectives.json",
  "diagnostics\intelligence_autonomy.json",
  "diagnostics\intelligence_dependency_graph.json",
  "diagnostics\intelligence_attention_budget.json",
  "diagnostics\intelligence_release_gate.json",
  "diagnostics\intelligence_root_cause_v5.json",
  "diagnostics\intelligence_predictive_v5.json",
  "diagnostics\intelligence_release_intelligence_v5.json",
  "diagnostics\intelligence_automation_discovery_v5.json",
  "diagnostics\intelligence_capability_trust_v5.json",
  "diagnostics\intelligence_engineering_v5.json",
  "diagnostics\intelligence_strategic_planner_v5.json",
  "diagnostics\runtime_bridge_status.json",
  "state\runtime_registry.json",
  "state\platform_service_registry.json",
  "state\config_registry.json",
  "diagnostics\platform_drift.json",
  "state\runtime_bridge.json",
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
