# Smart Auto Poster V3.0 platform features

## Destination collections
Reusable collections dynamically select eligible destinations by tags, account visibility, posting mode and forum status. Example:

```powershell
py .\app.py collection south_main --name "South Main" --include-tags "south,main" --exclude-tags "low_frequency" --access any
py .\app.py collections --preview
```

Campaigns can use collections:

```powershell
py .\app.py campaign-config CAMP_A --category evergreen --collections south_main --max-cycles 0
```

## Automation rules
Rules are deterministic operational rules, not Telegram-rate-limit bypass logic. Conditions/actions are JSON. Preview before applying:

```powershell
py .\app.py rule lowfreq --condition '{"tags_any":["low_frequency"]}' --action '{"min_interval_seconds":43200}'
py .\app.py rule-preview lowfreq
py .\app.py apply-rules --rule lowfreq --dry-run
py .\app.py apply-rules --rule lowfreq
```

Rules support minimum intervals, quiet hours, safe account affinity, protection, enable/never-auto-post and tag changes. A rule cannot silently enable a destination still awaiting review.

## Recommendations
Recommendations are generated from operational history and stay reviewable:

```powershell
py .\app.py recommendations --generate --hours 168
py .\app.py recommendation <id>
```

Only narrowly safe actions are directly applicable. Marketing/content strategy remains human-controlled.

## Cycle-limited campaigns
`max_cycles=0` means unlimited. A positive limit counts real enqueue cycles (duplicate-only enqueue attempts do not consume a cycle). After the final cycle, scheduling stops; the campaign archives only after outstanding jobs drain.

## Dual-account balancing
A destination with explicit `preferred_account=both` can be routed to an accessible authorized account using health, cooldown/pacing and least-recent usage. Explicit Primary or Secondary affinity continues to take precedence.
