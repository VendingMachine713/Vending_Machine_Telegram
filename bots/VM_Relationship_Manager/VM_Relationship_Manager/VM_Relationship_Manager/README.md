# VM Relationship Manager 4.0

VM Relationship Manager is the passive relationship-intelligence and lightweight CRM layer for the Vending Machine Telegram ecosystem.

Operating principle:

**observe → structure → score → detect change → estimate confidence → rank action → execute by exception**

It remains metadata-first. Telegram message bodies are not automatically archived.

## Start here

Use these most often:

- `/rm` — control centre
- `/brief` — concise executive relationship brief
- `/today` — ranked action inbox
- `/person @username` — full contact profile
- `/goals` — active relationship objectives
- `/segments` — dynamic CRM cohorts
- `/doctor` — operational health summary

## Relationship goals

Create a goal:

`/goal TELEGRAM_ID PRIORITY DUE title`

Example:

`/goal 123456 80 7d Confirm wholesale terms`

Use `none` instead of `7d` for no due date.

Update progress:

`/goalupdate GOAL_ID 50 Waiting for revised pricing`

Complete:

`/goalcomplete GOAL_ID`

Overdue goals automatically feed the attention and priority engines.

## Dynamic segments

`/segments`

Then:

`/segment commercial`

Example automatically derived segments include:

- `commercial`
- `high_value`
- `growing`
- `at_risk`
- `network_bridge`
- `new_active`
- `returned`
- `verification_needed`
- `reciprocity_watch`
- `opportunity_active`
- `followup_due`
- `priority_attention`
- `disengagement_risk`

## Conversation sessions

`/sessions TELEGRAM_ID`

Relationship Manager groups private direction/timing metadata into conversation sessions separated by a 30-minute inactivity gap. It reports session frequency, approximate session duration, initiation balance and session pattern.

Message content is not stored.

## Relationship outlook

`/outlook TELEGRAM_ID`

The outlook is a conservative metadata-based estimate. It combines existing health, momentum, learned cycle, recent acceleration, reciprocity, session activity and evidence depth.

It reports:

- disengagement risk
- re-engagement priority
- outlook label
- evidence confidence
- explainable contributing reasons

It is not a claim about another person's intentions.

## Data confidence

`/quality TELEGRAM_ID`

This separates **how much evidence the CRM has** from the score itself. New/low-history contacts are intentionally confidence-capped.

## Playbooks

`/playbook TELEGRAM_ID`

Playbooks suggest admin actions for relationship development, customers, suppliers, VIPs, dormant contacts, verification review and opportunities.

They do not automatically send contact messages.

## Advanced search

Examples:

- `/find segment:commercial risk>60`
- `/find confidence<50 score>50`
- `/find completeness<60`
- `/find sessions>=3`
- `/find outlook:watch`
- `/find goaldue`
- `/find type:supplier priority>40`

Saved views continue to work with `/saveview`, `/views` and `/view`.

## Operations

Telegram:

- `/doctor`
- `/diagnostics`
- `/backup`
- `/backups`

Local Windows fallback when the Telegram control bot cannot start:

`py .\VM_RM_LOCAL_DOCTOR.py`

The local doctor does not print the full configured phone number or Telegram secrets.

## Backups / migration

Before the first 4.0 schema migration, startup creates a verified SQLite-consistent `pre_v4_*.db` backup when required.

If an old safety backup exists but no longer matches the current live pre-upgrade database hash, a fresh safety backup is created instead of silently reusing stale data.

## Permanent paths

Bot:

`Vending_Machine_Telegram/bots/VM_Relationship_Manager/`

Database:

`Vending_Machine_Telegram/shared/exports/VM_Relationship_Manager/vm_relationships.db`

Backups:

`Vending_Machine_Telegram/shared/backups/VM_Relationship_Manager/`

Logs:

`Vending_Machine_Telegram/shared/logs/VM_Relationship_Manager/`

## Privacy

Relationship Manager stores structured CRM metadata, activity timing/counts, admin notes/memories/goals, opportunity data, risk-review state and derived intelligence.

It does not automatically archive Telegram message bodies.

Existing archive/exclude/forget-behaviour/purge controls remain available.
