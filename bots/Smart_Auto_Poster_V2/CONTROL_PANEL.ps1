$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
function Pause-VM { Write-Host ''; Read-Host 'Press Enter to continue' | Out-Null }
function Run-Cmd([string]$Command) { Write-Host ''; Write-Host "> $Command" -ForegroundColor DarkGray; Invoke-Expression $Command; Pause-VM }
function Ask-Campaign { return (Read-Host 'Campaign ID').Trim() }
function Ask-Content { return (Read-Host 'Content ID').Trim() }

while ($true) {
    Clear-Host
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' SMART AUTO POSTER V3.0 - PRODUCTION CONTROL CENTRE' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Host ' CORE / LIVE'
    Write-Host ' 1. Status dashboard'
    Write-Host ' 2. Health / readiness check'
    Write-Host ' 3. Validate database/config'
    Write-Host ' 4. Scan Telegram destinations'
    Write-Host ' 5. Show destinations needing review'
    Write-Host ' 6. Show enabled destinations'
    Write-Host ' 7. Show campaigns'
    Write-Host ' 8. Show queue'
    Write-Host ' 9. Run one queue job (controlled test)'
    Write-Host '10. START Smart Auto Poster V3.0 service'
    Write-Host ''
    Write-Host ' SAFETY / MAINTENANCE'
    Write-Host '11. Backup database/config/cache'
    Write-Host '12. Export destinations CSV'
    Write-Host '13. Run full self-tests'
    Write-Host '14. Open content folder'
    Write-Host '15. Open bot folder'
    Write-Host '16. Setup / upgrade environment'
    Write-Host '17. Import existing destination config'
    Write-Host '18. Safety status'
    Write-Host '19. PAUSE outbound posting'
    Write-Host '20. RESUME outbound posting'
    Write-Host '21. Check Telegram account identities'
    Write-Host '22. Re-login SECONDARY Telegram account'
    Write-Host ''
    Write-Host ' CAMPAIGNS / CONTENT'
    Write-Host '23. Import content inbox'
    Write-Host '24. Create campaign (wizard)'
    Write-Host '25. Preview campaign (marks READY)'
    Write-Host '26. Manage/list campaign variants'
    Write-Host '27. Simulate next 24 hours'
    Write-Host '28. Queue + failure dashboard'
    Write-Host '29. Retry failed jobs'
    Write-Host '30. Operational summary (24h)'
    Write-Host '31. Open content inbox'
    Write-Host '32. Install Windows auto-start'
    Write-Host '33. Remove Windows auto-start'
    Write-Host '34. Post Now (preview + confirm)'
    Write-Host '35. Clone a campaign'
    Write-Host ''
    Write-Host ' V3.0 AUTONOMOUS / CONTROL CENTRE'
    Write-Host '36. Set campaign lifecycle (draft/ready/active/paused/archived)'
    Write-Host '37. List campaign templates'
    Write-Host '38. Create campaign from template'
    Write-Host '39. Configure schedule (interval/daily/one-off/off)'
    Write-Host '40. Cross-campaign minimum-gap rule'
    Write-Host '41. Bulk destination action by tag'
    Write-Host '42. Queue job manager (retry/cancel/defer/mark-sent)'
    Write-Host '43. Cancel pending jobs for a campaign'
    Write-Host '44. Queue capacity / guardrails'
    Write-Host '45. Analytics report (7 days)'
    Write-Host '46. Watchdog / heartbeat status'
    Write-Host '47. Database integrity check'
    Write-Host '48. Vacuum database'
    Write-Host '49. Generate SAFE diagnostic bundle'
    Write-Host '50. Media cache status'
    Write-Host '51. Clear media cache'
    Write-Host '52. Telegram Admin Bot status / open .env'
    Write-Host '53. Start Telegram Admin Bot only'
    Write-Host '54. Install/refresh master update system'
    Write-Host '55. Roll back last master update'
    Write-Host '56. Admin audit log'
    Write-Host '57. Run maintenance/cleanup now'
    Write-Host '58. Windows auto-start status'
    Write-Host '59. Content lifecycle (ready/disabled/archived/rejected)'
    Write-Host '60. Content tags'
    Write-Host '61. Update history'
    Write-Host ''
    Write-Host ' V3.0 COLLECTIONS / RULES / INTELLIGENCE'
    Write-Host '62. List destination collections + previews'
    Write-Host '63. Create/update destination collection'
    Write-Host '64. Configure campaign V3 category/collections/cycle limit'
    Write-Host '65. List automation rules'
    Write-Host '66. Create/update automation rule (JSON)'
    Write-Host '67. Preview/apply automation rule'
    Write-Host '68. Generate/list smart recommendations'
    Write-Host '69. Apply/dismiss recommendation'
    Write-Host '70. Daily V3 report'
    Write-Host '71. Weekly V3 report'
    Write-Host '72. V3 release verification (tests + validate + integrity)'
    Write-Host ' 0. Exit'
    Write-Host ''
    $choice = Read-Host 'Choose'
    switch ($choice) {
        '1'  { Run-Cmd 'py .\app.py status' }
        '2'  { Run-Cmd 'py .\app.py health' }
        '3'  { Run-Cmd 'py .\app.py validate' }
        '4'  { Run-Cmd 'py .\app.py scan' }
        '5'  { Run-Cmd 'py .\app.py destinations --review' }
        '6'  { Run-Cmd 'py .\app.py destinations --enabled' }
        '7'  { Run-Cmd 'py .\app.py campaigns' }
        '8'  { Run-Cmd 'py .\app.py queue --limit 50' }
        '9'  { Run-Cmd 'py .\app.py worker --once' }
        '10' { Write-Host ''; Write-Host 'Starting V3.0 scheduler + worker + watchdog + recovery + optional Admin Bot. Ctrl+C stops cleanly.' -ForegroundColor Yellow; py .\app.py run; Pause-VM }
        '11' { Run-Cmd 'py .\app.py backup' }
        '12' { Run-Cmd 'py .\app.py export-destinations' }
        '13' { Run-Cmd 'py -m unittest discover -s tests -v' }
        '14' { Start-Process explorer.exe (Join-Path $Root 'content') }
        '15' { Start-Process explorer.exe $Root }
        '16' { & (Join-Path $Root 'run_setup.ps1'); Pause-VM }
        '17' { Run-Cmd 'py .\app.py import-config' }
        '18' { Run-Cmd 'py .\app.py safety-status' }
        '19' { Run-Cmd 'py .\app.py pause --reason "control panel manual pause"' }
        '20' { Run-Cmd 'py .\app.py resume' }
        '21' { Run-Cmd 'py .\app.py accounts-check' }
        '22' { Write-Host ''; Write-Host 'This backs up the existing Secondary session before login.' -ForegroundColor Yellow; $confirm=Read-Host 'Type YES to continue'; if($confirm -eq 'YES'){Run-Cmd 'py .\app.py login-account secondary --reset'} }
        '23' { Run-Cmd 'py .\app.py import-content' }
        '24' { Run-Cmd 'py .\app.py campaign-wizard' }
        '25' { $c=Ask-Campaign; if($c){Run-Cmd "py .\app.py preview `"$c`""} }
        '26' { $c=Ask-Campaign; if($c){Run-Cmd "py .\app.py campaign-content `"$c`""} }
        '27' { Run-Cmd 'py .\app.py simulate --hours 24' }
        '28' { Run-Cmd 'py .\app.py queue-summary --limit 30' }
        '29' { $c=Read-Host 'Campaign ID (blank = ALL failed)'; if($c){Run-Cmd "py .\app.py retry-failed --campaign `"$c`""}else{Run-Cmd 'py .\app.py retry-failed'} }
        '30' { Run-Cmd 'py .\app.py daily-summary --hours 24' }
        '31' { Start-Process explorer.exe (Join-Path $Root 'content\inbox') }
        '32' { & (Join-Path $Root 'INSTALL_AUTOSTART.ps1'); Pause-VM }
        '33' { & (Join-Path $Root 'REMOVE_AUTOSTART.ps1'); Pause-VM }
        '34' { $c=Ask-Campaign; if($c){ py .\app.py post-now $c --dry-run; $confirm=Read-Host 'Type SEND to enqueue now'; if($confirm -eq 'SEND'){Run-Cmd "py .\app.py post-now `"$c`""}else{Pause-VM} } }
        '35' { $src=Read-Host 'Source campaign ID'; $dst=Read-Host 'New campaign ID'; if($src -and $dst){Run-Cmd "py .\app.py clone-campaign `"$src`" `"$dst`""} }
        '36' { $c=Ask-Campaign; $st=Read-Host 'State: draft/ready/active/paused/archived'; if($c -and $st){Run-Cmd "py .\app.py campaign-state `"$c`" `"$st`""} }
        '37' { Run-Cmd 'py .\app.py templates' }
        '38' { $t=Read-Host 'Template: evergreen/daily/announcement/one_off/rotating_ads'; $c=Ask-Campaign; $n=Read-Host 'Campaign name'; $ct=Ask-Content; $tags=Read-Host 'Include destination tags'; if($t -and $c -and $ct){Run-Cmd "py .\app.py create-template `"$t`" `"$c`" `"$n`" `"$ct`" --tags `"$tags`""} }
        '39' { $c=Ask-Campaign; Write-Host '1 interval | 2 daily | 3 one-off | 4 off'; $m=Read-Host 'Choose'; if($m -eq '1'){$v=Read-Host 'Interval minutes';Run-Cmd "py .\app.py schedule `"$c`" --interval-minutes $v"}elseif($m -eq '2'){$v=Read-Host 'Times comma-separated HH:MM';Run-Cmd "py .\app.py schedule `"$c`" --daily-times `"$v`""}elseif($m -eq '3'){$v=Read-Host 'Date/time YYYY-MM-DDTHH:MM';Run-Cmd "py .\app.py schedule `"$c`" --once-at `"$v`""}elseif($m -eq '4'){Run-Cmd "py .\app.py schedule `"$c`" --off"} }
        '40' { $a=Read-Host 'Campaign A'; $b=Read-Host 'Campaign B'; $mins=Read-Host 'Minimum gap minutes'; $both=Read-Host 'Apply both directions? y/N'; $flag=if($both -match '^[Yy]'){'--both'}else{''}; Run-Cmd "py .\app.py campaign-gap `"$a`" `"$b`" --minutes $mins $flag" }
        '41' { $tag=Read-Host 'Existing destination tag'; Write-Host 'Example flags: --disable   OR --protect   OR --never-auto-post   OR --add-tag NAME'; $flags=Read-Host 'Flags'; Run-Cmd "py .\app.py bulk-destinations `"$tag`" $flags" }
        '42' { $id=Read-Host 'Queue job ID'; Write-Host '1 retry | 2 cancel | 3 defer | 4 mark sent'; $a=Read-Host 'Choose'; if($a -eq '1'){Run-Cmd "py .\app.py job $id --retry"}elseif($a -eq '2'){Run-Cmd "py .\app.py job $id --cancel"}elseif($a -eq '3'){$m=Read-Host 'Defer minutes';Run-Cmd "py .\app.py job $id --defer-minutes $m"}elseif($a -eq '4'){Run-Cmd "py .\app.py job $id --mark-sent"} }
        '43' { $c=Ask-Campaign; if($c){Run-Cmd "py .\app.py cancel-campaign-jobs `"$c`""} }
        '44' { Run-Cmd 'py .\app.py queue-capacity' }
        '45' { Run-Cmd 'py .\app.py analytics --hours 168' }
        '46' { Run-Cmd 'py .\app.py watchdog' }
        '47' { Run-Cmd 'py .\app.py integrity' }
        '48' { $confirm=Read-Host 'Type VACUUM to compact the database'; if($confirm -eq 'VACUUM'){Run-Cmd 'py .\app.py vacuum'} }
        '49' { Run-Cmd 'py .\app.py diagnostics' }
        '50' { Run-Cmd 'py .\app.py cache-status' }
        '51' { $a=Read-Host 'Account primary/secondary or blank for BOTH'; if($a){Run-Cmd "py .\app.py clear-cache --account $a"}else{Run-Cmd 'py .\app.py clear-cache'} }
        '52' { py .\app.py admin-status; Write-Host ''; Write-Host 'Configure ADMIN_BOT_TOKEN + ADMIN_USER_IDS locally in .env. Never paste the token into chat.' -ForegroundColor Yellow; $open=Read-Host 'Open .env in Notepad? y/N'; if($open -match '^[Yy]'){Start-Process notepad.exe (Join-Path $Root '.env')}; Pause-VM }
        '53' { Write-Host 'This starts ONLY the private Telegram admin bot. Ctrl+C stops it.' -ForegroundColor Yellow; py .\app.py admin-bot; Pause-VM }
        '54' { & (Join-Path $Root 'INSTALL_MASTER_UPDATER.ps1'); Pause-VM }
        '55' { $master=(Resolve-Path (Join-Path $Root '..\..')).Path; $rb=Join-Path $master 'ROLLBACK_LAST_UPDATE.ps1'; if(Test-Path $rb){& $rb}else{Write-Host 'Rollback script not installed. Run option 54 first.' -ForegroundColor Yellow}; Pause-VM }
        '56' { Run-Cmd 'py .\app.py audit-log --limit 50' }
        '57' { Run-Cmd 'py .\app.py maintenance' }
        '58' { & (Join-Path $Root 'AUTOSTART_STATUS.ps1'); Pause-VM }
        '59' { $c=Ask-Content; $st=Read-Host 'State: ready/disabled/archived/rejected'; if($c -and $st){Run-Cmd "py .\app.py content-state `"$c`" `"$st`""} }
        '60' { $c=Ask-Content; $add=Read-Host 'Tag to add (blank none)'; $remove=Read-Host 'Tag to remove (blank none)'; $flags=''; if($add){$flags += " --add-tag `"$add`""}; if($remove){$flags += " --remove-tag `"$remove`""}; Run-Cmd "py .\app.py content-tags `"$c`" $flags" }
        '61' { Run-Cmd 'py .\app.py update-history --limit 50' }
        '62' { Run-Cmd 'py .\app.py collections --preview' }
        '63' {
            $id=(Read-Host 'Collection ID').Trim(); if(-not $id){Pause-VM; continue}
            $name=Read-Host 'Display name (blank = ID)'; $inc=Read-Host 'Include tags comma-separated (blank = any)'; $exc=Read-Host 'Exclude tags comma-separated';
            $access=Read-Host 'Access any/primary/secondary/both [any]'; if(-not $access){$access='any'}
            $mode=Read-Host 'Mode any/photo/text [any]'; if(-not $mode){$mode='any'}
            $forum=Read-Host 'Forum only? y/N'; $prot=Read-Host 'Allow protected destinations? y/N'
            $flags=''; if($name){$flags += " --name `"$name`""}; if($inc){$flags += " --include-tags `"$inc`""}; if($exc){$flags += " --exclude-tags `"$exc`""};
            $flags += " --access $access --mode $mode"; if($forum -match '^[Yy]'){$flags += ' --forum-only'}; if($prot -match '^[Yy]'){$flags += ' --include-protected'}
            Run-Cmd "py .\app.py collection `"$id`" $flags"
        }
        '64' {
            $c=Ask-Campaign; if(-not $c){Pause-VM; continue}; $cat=Read-Host 'Category (blank = leave unchanged)'; $cols=Read-Host 'Collections comma-separated (blank = leave unchanged)'; $cycles=Read-Host 'Max cycles (blank = leave unchanged, 0 = unlimited)';
            $flags=''; if($cat){$flags += " --category `"$cat`""}; if($cols){$flags += " --collections `"$cols`""}; if($cycles -ne ''){$flags += " --max-cycles $cycles"};
            if(-not $flags){Run-Cmd "py .\app.py campaign-config `"$c`""}else{Run-Cmd "py .\app.py campaign-config `"$c`" $flags"}
        }
        '65' { Run-Cmd 'py .\app.py rules' }
        '66' {
            $id=(Read-Host 'Rule ID').Trim(); if(-not $id){Pause-VM; continue}; $name=Read-Host 'Rule name'; $condition=Read-Host 'Condition JSON e.g. {"tags_any":["low_frequency"]}'; $action=Read-Host 'Action JSON e.g. {"min_interval_seconds":43200}'; $pri=Read-Host 'Priority [100]'; if(-not $pri){$pri=100};
            Run-Cmd "py .\app.py rule `"$id`" --name `"$name`" --condition '$condition' --action '$action' --priority $pri"
        }
        '67' {
            $id=(Read-Host 'Rule ID').Trim(); if(-not $id){Pause-VM; continue}; py .\app.py rule-preview $id; $go=Read-Host 'Type APPLY to apply this rule'; if($go -eq 'APPLY'){Run-Cmd "py .\app.py apply-rules --rule `"$id`""}else{Pause-VM}
        }
        '68' { Run-Cmd 'py .\app.py recommendations --generate --hours 168 --status open --limit 50' }
        '69' {
            $id=(Read-Host 'Recommendation ID').Trim(); if(-not $id){Pause-VM; continue}; $a=Read-Host 'Type APPLY or DISMISS (blank=view)'; if($a -eq 'APPLY'){Run-Cmd "py .\app.py recommendation `"$id`" --apply"}elseif($a -eq 'DISMISS'){Run-Cmd "py .\app.py recommendation `"$id`" --dismiss"}else{Run-Cmd "py .\app.py recommendation `"$id`""}
        }
        '70' { Run-Cmd 'py .\app.py report' }
        '71' { Run-Cmd 'py .\app.py report --weekly' }
        '72' { Write-Host ''; Write-Host 'Running V3.0 release verification...' -ForegroundColor Yellow; py -m compileall -q .; if($LASTEXITCODE -eq 0){py -m unittest discover -s tests -q}; if($LASTEXITCODE -eq 0){py .\app.py validate}; if($LASTEXITCODE -eq 0){py .\app.py integrity}; Pause-VM }
        '0' { return }
        default { Start-Sleep -Seconds 1 }
    }
}
