# VM Brain Canonical Readiness Health

## Purpose

Canonical readiness now includes passive evidence-health metrics derived from the existing canonical inference ledger. No new persistence, scheduler, Telegram action or execution authority is introduced.

## Metrics

The evidence-health surface reports:

- total canonical inference events;
- distinct canonical subjects;
- newest and oldest evidence timestamps;
- newest evidence age;
- observation span;
- events observed in the last 24 hours, 7 days and 30 days;
- latest suppressed-subject count and ratio;
- staleness status.

## Health states

`NO_EVIDENCE`
: No dated canonical inference evidence is available.

`ACTIVE_SHADOW`
: The newest canonical inference is within the configured freshness window.

`STALE`
: Canonical inference evidence exists but the newest sample is older than the configured freshness window (72 hours by default).

## Operator visibility

Mission Control exposes `headline.canonical_evidence_health` and `attention.canonical_evidence_stale`. The full metric set remains under `canonical.evidence_health`.

## Safety

This layer is read-only. Missing state remains missing, and standalone health evaluation does not initialise a database. It creates no recommendation, approval or action. `automatic_execution` remains false.
