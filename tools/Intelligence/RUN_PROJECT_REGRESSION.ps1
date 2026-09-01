param(
 [string]$Root,
 [string]$OutputName='intelligence_regression.json',
 [string]$BaselineFile,
 [switch]$CaptureBaseline
)
$ErrorActionPreference='Stop'
if(-not $Root){$Root=Resolve-Path (Join-Path $PSScriptRoot '..\..')}
else{$Root=(Resolve-Path $Root).Path}
$Diag=Join-Path $Root 'diagnostics'
New-Item -ItemType Directory -Force -Path $Diag|Out-Null
$Discover=Join-Path $PSScriptRoot 'DISCOVER_BOT_TESTS.py'
$Runner=Join-Path $PSScriptRoot 'RUN_TEST_SUITE.py'

$BaselineFailed=@()
$BaselineResults=@{}
if(-not $CaptureBaseline){
 if(-not $BaselineFile){
  $candidate=Join-Path $Diag 'intelligence_regression_preinstall.json'
  if(Test-Path $candidate){$BaselineFile=$candidate}
 }
 if($BaselineFile -and (Test-Path $BaselineFile)){
  try{
   $b=Get-Content $BaselineFile -Raw|ConvertFrom-Json
   $BaselineFailed=@($b.failed_test_suites)
   foreach($row in @($b.results)){$BaselineResults[$row.bot]=$row}
  }catch{}
 }else{
  $full=Join-Path $Diag 'full_validation.json'
  if(Test-Path $full){try{$BaselineFailed=@((Get-Content $full -Raw|ConvertFrom-Json).failed_test_suites)}catch{}}
 }
}

$results=@();$newFailures=@();$currentFailures=@();$surfaceChanges=@()
$Bots=Get-ChildItem (Join-Path $Root 'bots') -Directory | Sort-Object Name
foreach($bot in $Bots){
 $discoveryRaw=py $Discover --root "$Root" --bot "$($bot.Name)"
 if($LASTEXITCODE-ne 0){throw "Unable to discover canonical tests for $($bot.Name)."}
 try{$discovery=$discoveryRaw|ConvertFrom-Json}catch{throw "Invalid test discovery response for $($bot.Name): $discoveryRaw"}
 if(-not $discovery.available){
  $results += [pscustomobject]@{bot=$bot.Name;status='NO_TESTS';exit_code=0;test_dir=$null;
   baseline_failure=($BaselineFailed -contains $bot.Name);discovery_reason=$discovery.reason;
   test_count=0;test_ids=@();failed_test_ids=@();error_test_ids=@();skipped_test_ids=@();
   test_ids_added=@();test_ids_removed=@();test_surface_changed=$false}
  continue
 }
 $testDir=$discovery.test_dir;$suiteRoot=$discovery.suite_root
 $suiteJson=Join-Path $Diag ("intelligence_suite_"+($bot.Name -replace '[^A-Za-z0-9_.-]','_')+".json")
 Write-Host "[TEST] $($bot.Name) -> $testDir [$($discovery.reason)]" -ForegroundColor Cyan
 py $Runner --root "$Root" --suite-root "$suiteRoot" --test-dir "$testDir" --bot-root "$($bot.FullName)" --result-json "$suiteJson"
 $rc=$LASTEXITCODE
 $machine=$null
 if(Test-Path $suiteJson){try{$machine=Get-Content $suiteJson -Raw|ConvertFrom-Json}catch{}}
 $ids=@();$failedIds=@();$errorIds=@();$skippedIds=@()
 if($machine){
  $ids=@($machine.test_ids);$failedIds=@($machine.failed_test_ids);$errorIds=@($machine.error_test_ids);$skippedIds=@($machine.skipped_test_ids)
 }
 $baselineFailure=($BaselineFailed -contains $bot.Name)
 $added=@();$removed=@()
 if(-not $CaptureBaseline -and $BaselineResults.ContainsKey($bot.Name)){
  $baseIds=@($BaselineResults[$bot.Name].test_ids)
  if($baseIds.Count -gt 0 -or $ids.Count -gt 0){
   $added=@($ids|Where-Object {$_ -notin $baseIds})
   $removed=@($baseIds|Where-Object {$_ -notin $ids})
  }
 }
 $surfaceChanged=($added.Count -gt 0 -or $removed.Count -gt 0)
 if($surfaceChanged){$surfaceChanges += $bot.Name}
 if($CaptureBaseline){$status=if($rc -eq 0){'PASS'}else{'BASELINE_FAIL'}}
 else{$status=if($surfaceChanged){'TEST_SURFACE_CHANGED'}elseif($rc -eq 0){'PASS'}elseif($baselineFailure){'KNOWN_FAIL'}else{'NEW_FAIL'}}
 if($rc -ne 0){$currentFailures += $bot.Name}
 if(-not $CaptureBaseline -and $rc -ne 0 -and -not $baselineFailure){$newFailures += $bot.Name}
 $results += [pscustomobject]@{
  bot=$bot.Name;status=$status;exit_code=$rc;test_dir=$testDir;baseline_failure=$baselineFailure;
  discovery_reason=$discovery.reason;discovery_score=$discovery.score;
  test_count=$ids.Count;test_ids=$ids;failed_test_ids=$failedIds;error_test_ids=$errorIds;skipped_test_ids=$skippedIds;
  test_ids_added=$added;test_ids_removed=$removed;test_surface_changed=$surfaceChanged
 }
}
$out=[ordered]@{
 schema_version=4
 completed_at_utc=[DateTime]::UtcNow.ToString('o')
 mode=if($CaptureBaseline){'baseline'}else{'comparison'}
 baseline_file=$BaselineFile
 baseline_failed_test_suites=@($BaselineFailed)
 failed_test_suites=@($currentFailures)
 new_failed_test_suites=@($newFailures)
 test_surface_changed_suites=@($surfaceChanges)
 all_test_suites_ok=($currentFailures.Count -eq 0)
 stable_test_surface=($surfaceChanges.Count -eq 0)
 no_new_regressions=($newFailures.Count -eq 0 -and $surfaceChanges.Count -eq 0)
 results=$results
}
$out|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Diag $OutputName) -Encoding UTF8
if($CaptureBaseline){
 if($currentFailures.Count -gt 0){Write-Host "[BASELINE] Existing failing suites: $($currentFailures -join ', ')" -ForegroundColor Yellow}
 else{Write-Host '[BASELINE] All discovered canonical suites passed before installation.' -ForegroundColor Green}
 Write-Host ("[BASELINE] Captured exact test IDs for {0} suite(s)." -f @($results|Where-Object {$_.status -ne 'NO_TESTS'}).Count) -ForegroundColor Green
 exit 0
}
if($surfaceChanges.Count -gt 0){
 Write-Host "[FAIL] Canonical test surface changed during deployment: $($surfaceChanges -join ', ')" -ForegroundColor Red
 foreach($r in $results|Where-Object {$_.test_surface_changed}){
  Write-Host ("  {0}: +{1} -{2}" -f $r.bot,$r.test_ids_added.Count,$r.test_ids_removed.Count) -ForegroundColor Red
 }
 exit 3
}
if($newFailures.Count -gt 0){Write-Host "[FAIL] New regression suites: $($newFailures -join ', ')" -ForegroundColor Red;exit 2}
if($currentFailures.Count -gt 0){Write-Host "[WARN] Pre-existing failing suites remain: $($currentFailures -join ', ')" -ForegroundColor Yellow}
else{Write-Host '[OK] All discovered canonical bot test suites passed with a stable exact test surface.' -ForegroundColor Green}
exit 0
