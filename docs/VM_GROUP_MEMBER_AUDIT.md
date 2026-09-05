# Mission Control Group Member Audit v1

Updated: 2026-09-06

## Purpose

The Group Member Audit is a passive Mission Control surface for understanding the visible composition of a Telegram group without using bulk direct messages as a bot-detection mechanism.

The v1 read model is intentionally conservative. It consumes canonical audit observations produced by approved data collectors and presents:

- summary cards;
- confidence/category filters;
- a bounded member table;
- a member detail/evidence panel;
- attention items;
- audit history;
- safe operator actions.

It does **not** enumerate Telegram members itself, send messages, remove members, create automatic Relationship Manager records, or execute outreach.

## Data contract

Producer: `Universal_Search`

Supported canonical event types:

- `intelligence.observation.group_member_audit.member`
- `intelligence.observation.group_member_audit.snapshot`

Member observations use a canonical Telegram user subject and include the canonical group subject in safe attributes.

Snapshot observations use a canonical Telegram chat subject.

Raw Telegram numeric IDs, usernames, display names, message text, session data and credentials are not exposed by the shared Mission Control read model.

## Categories

- `LIKELY_HUMAN`
- `BOT_ACCOUNT`
- `DELETED`
- `UNCERTAIN`
- `KNOWN_CONTACT`
- `RESTRICTED`

Unknown producer categories fail closed to `UNCERTAIN`.

## Confidence labels

- `VERY_HIGH`
- `HIGH`
- `MEDIUM`
- `LOW`
- `INSUFFICIENT_EVIDENCE`

Unknown confidence labels fail closed to `INSUFFICIENT_EVIDENCE`.

A Telegram account merely lacking the Telegram bot flag is not treated as proof that it is human.

## Mission Control layout

The terminal/operator surface exposes:

1. group/header and audit freshness;
2. summary cards for total, likely human, bot, deleted, uncertain, known and restricted;
3. attention items;
4. category/confidence/known/review/activity filters;
5. bounded member table;
6. detail panel with evidence reason codes;
7. audit history;
8. safe operator actions;
9. explicit safety boundary.

Run:

`py tools\vm_brain_phase2.py group-audit`

The normal Mission Control JSON also exposes the complete read model under:

`group_member_audit`

## Attention rules

The v1 read model raises bounded diagnostic attention for:

- bot concentration at or above 25%;
- uncertain share at or above 20%;
- deleted share at or above 10%;
- members explicitly marked for manual review;
- audit coverage below 80%;
- stale audit snapshots.

These are diagnostic flags, not removal or outreach instructions.

## Operator actions

The read model advertises only safe workflow intents:

- view evidence;
- mark for manual review;
- add operator note;
- open Relationship Manager profile;
- export filtered results;
- add to an approved outreach shortlist.

The audit surface deliberately has no bulk-message action.

## Safety boundary

The following remain disabled:

- automatic outreach;
- automatic acceptance;
- automatic execution;
- external action authority.

The read model is idempotent and does not write events or recommendations when opened.

## Next milestone

After real canonical audit evidence exists, the next safe step is a producer-side Group Scanner / Universal Search adapter that gathers only Telegram metadata the connected account is legitimately permitted to inspect, emits the canonical member/snapshot events above, handles FloodWait conservatively, and remains no-send by default.
