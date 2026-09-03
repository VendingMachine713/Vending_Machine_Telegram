# VM Relationship Manager Changelog

## 4.0.0 — 2026-09-01

This release accumulates the full 3.1 → 3.9 roadmap internally and consolidates it as one dependency-closed direct-drop production update.

### v3.1 — Relationship Goals
- Added contact-linked goals with priority, target time, progress, next step and completion state.
- Added `/goals`, `/goal`, `/goalupdate` and `/goalcomplete`.
- Overdue goals feed the existing attention queue and combined relationship priority engine.
- Goal completion resolves goal-due attention automatically.

### v3.2 — Dynamic CRM Segmentation
- Added automatically computed metadata-based segments including commercial, high-value, growing, at-risk, network bridge, new-active, returned, verification-needed, reciprocity-watch, opportunity-active and follow-up-due.
- Added `/segments` and `/segment KEY`.
- Added segment filters to advanced CRM search.

### v3.3 — Conversation Session Intelligence
- Added private conversation-session analytics derived only from existing direction/timing metadata.
- Sessions are separated by a 30-minute inactivity gap.
- Added 30-day session count, average messages/session, median duration, who usually initiates and initiation balance.
- Added `/sessions TELEGRAM_ID`.
- Message bodies remain unstored.

### v3.4 — Conservative Relationship Outlook
- Added explainable disengagement-risk and re-engagement-priority estimates.
- Outlook uses health, learned-cycle overdue state, momentum, interaction acceleration, reciprocity and conversation-session quality.
- Added evidence confidence and explicit wording that the outlook is not a claim about a person's intentions.
- Added `/outlook TELEGRAM_ID` and `risk>` search filters.

### v3.5 — Intelligence Confidence / Data Quality
- Added per-contact data completeness and evidence-confidence scoring.
- Confidence is capped for contacts with very little activity history so the CRM cannot present early guesses as mature intelligence.
- Added `/quality TELEGRAM_ID`, `confidence>` / `completeness>` / `lowconfidence` search filters.

### v3.6 — Relationship Playbooks
- Added metadata-safe recommended admin playbooks for relationship development, customer nurture, supplier management, VIP nurture, dormant revival, verification review and opportunity progression.
- Playbooks recommend actions only; they never message contacts automatically.
- Added `/playbook TELEGRAM_ID` and profile buttons.

### v3.7 — Executive Briefing
- Added `/brief`, combining top priorities, overdue goals, high-disengagement-risk contacts, unhealthy opportunities, growing relationships and pending risk reviews.
- Added daily brief snapshots to maintenance for historical operating context.
- Dashboard now exposes Brief, Goals, Segments and at-risk views directly.

### v3.8 — Search / Reporting / Integration Expansion
- Advanced search now understands segment, outlook, risk, confidence, completeness, sessions and goal-due filters.
- Weekly/monthly reports now include goals, high-risk outlook counts, data-confidence averages, session activity and top dynamic segments.
- Privacy-safe contact-index exports now include outlook, confidence, session pattern, segments and active goals.
- No relationship memories or message bodies are added to the integration export.

### v3.9 — Operations & Upgrade Hardening
- Added `/doctor` plus `VM_RM_LOCAL_DOCTOR.py` for local startup/import/database checks when Telegram control is unavailable.
- Pre-v4 safety backups are SQLite-consistent and verified before migration.
- A prior pre-v4 backup is reused only when its manifest proves it matches the current live pre-upgrade database hash; changed live data triggers a fresh safety backup.
- Maintenance computes dependent intelligence in a deterministic order: behaviour/network → sessions → data quality → outlook → automation/priority → segments.
- Added bounded daily brief history.

### v4.0 — Consolidation
- Schema version upgraded non-destructively to 4.0.0.
- Direct migrations tested from v3.0 and v2-era databases while preserving contacts and tags.
- Major release package is dependency-closed: all production Python modules needed by v4 are included to prevent the missing-module packaging failure seen during the v3 rollout.
- Existing `.env`, BotFather token, Telegram account sessions, database, notes, tags, contacts, opportunities, goals and history are not packaged or replaced.

## Validation
- Production-module compile pass.
- 75 Telegram command-handler targets statically verified.
- v4 startup smoke test.
- v3 → v4 migration test.
- v2-era → v4 migration test.
- scheduler/maintenance cycle test.
- pre-upgrade verified backup and stale-backup-hash test.
- admin rendering test.
- goals/priority/attention integration test.
- session/outlook/data-confidence/segment test.
- private-chat vs group/network isolation test.
- v4 contact-index privacy/export test.
