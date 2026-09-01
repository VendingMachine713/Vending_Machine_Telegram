# Smart Auto Poster V4 Operations

## Round behaviour
1. Scheduler creates at most one unresolved queue row per eligible group.
2. Pass 1 claims untouched groups in due order.
3. Retry-safe timing or transient failures update the same row to `deferred` or `retry`, increment its pass number, and return control to the worker immediately.
4. Pass 2 remains blocked until no Pass 1 row for that run is active.
5. A definitive SENT outcome closes the row and suppresses any legacy pre-send duplicate for the same group.
6. UNCERTAIN remains an evidence/reconciliation state and blocks other work for that group.

## Per-post pipeline
Typical phases are: queued â†’ validating destination â†’ timing check â†’ content validation â†’ account selection â†’ payload preparation â†’ Telegram send boundary â†’ destination resolution â†’ media preparation/upload (photo) or text send â†’ acknowledgement â†’ sent.

Use `py .\app.py job-timeline <id>` for the checklist and durable history.

## Mixed-mode routing
- `text`: requires a non-empty caption; media is not sent.
- `photo`: requires 1..10 media files; caption is optional.
- Telegram rights discovered during scans are merged across both user accounts. If either reachable account can send a format, that capability remains available.
- One-format restrictions automatically align the destination mode. Neither-format destinations fail closed into review.

## Operator surfaces
- CLI live run: `py .\app.py progress --campaign main_production_01 --watch --interval 5`
- CLI Mission Control: `py .\app.py mission-control --campaign main_production_01`
- CLI post history: `py .\app.py job-timeline <id>`
- Telegram: `/progress`, `/mission`, `/post <id>`
- Control Panel: options 89, 90 and 91.

## Safety
Never generically retry UNCERTAIN. Reconcile it from Telegram-history evidence. A SlowMode/FloodWait row should remain one row with a later due time and higher pass number; do not create a replacement post.
