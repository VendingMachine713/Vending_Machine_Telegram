# VM Brain — Unified Canonical Review Audit Timeline

## Purpose

The canonical review audit timeline is a passive operator-facing projection that connects the complete governed intelligence chain:

`canonical inference → recommendation proposal → expiry/supersession → operator decision → completion → verified outcome → calibration`

It reuses the existing VM Platform event ledger, recommendation governance state, learning outcomes and canonical calibration. It does **not** create a second governance or learning framework.

## Read-only design

`shared.vm_core.canonical_review_audit` opens `state/vm_platform.sqlite3` in SQLite read-only mode and enables `PRAGMA query_only=ON`. If the database or required tables are missing, the query returns `UNAVAILABLE` and does not initialise or migrate the platform database.

The audit surface never accepts recommendations, executes Telegram actions, schedules external work, changes thresholds, changes rules, or grants action authority.

## Timeline stages

The projection recognises these durable records:

- `intelligence.inference.relationship_reengagement_opportunity` → `INFERENCE`
- `recommendation.proposed` → `PROPOSAL`
- `recommendation.supersedes` → `SUPERSESSION`
- `recommendation.accepted` → `DECISION / ACCEPTED`
- `recommendation.dismissed` → `DECISION / DISMISSED`
- `recommendation.completed` → `COMPLETION / COMPLETED`
- `recommendation.expired` → `EXPIRY / EXPIRED`
- `recommendation.outcome_recorded` → `OUTCOME`
- current canonical review calibration report → read-only `CALIBRATION` snapshot after a verified outcome

Superseding recommendations retain `lineage.supersedes`; predecessor timelines expose `lineage.superseded_by` when the replacement is present in the query window.

## Privacy and identifiers

Operator output is deliberately curated. The audit API does not return arbitrary `payload_json` or `evidence_json` fields. Subjects must be canonical hashed IDs such as `telegram:chat:<digest>`; malformed/non-canonical subjects are skipped. Recommendation keys must use the canonical namespace.

This prevents raw Telegram IDs/contact IDs that may exist elsewhere in operational storage from leaking through the audit surface.

## Failure behaviour and idempotency

Malformed JSON, invalid event metadata and invalid recommendation rows fail safely. The result is marked `PARTIAL`, `malformed_rows` is incremented, and valid history remains visible. Missing databases/tables return `UNAVAILABLE`.

Semantically duplicate audit events are collapsed in the read model and counted in `duplicate_events_ignored`. The underlying event ledger is never rewritten.

## Mission Control

`mission_control()` exposes the projection under `canonical_review_audit`, including:

- audit status
- stage counts
- concise recent history
- malformed-row count
- supersession lineage
- explicit safety/authority flags

Headline fields provide `canonical_review_audit_status` and `canonical_review_audit_events`; malformed rows are surfaced under `attention`.

## Safety invariants

The following remain disabled:

- automatic recommendation acceptance
- Telegram/external execution
- automatic threshold changes
- automatic rule changes
- external action authority

Controlled autonomy remains a later roadmap phase and is not enabled by this milestone.
