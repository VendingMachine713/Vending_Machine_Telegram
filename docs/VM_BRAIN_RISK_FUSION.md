# VM Brain Risk Fusion

## Purpose

Risk Fusion combines canonical VM Guard risk with passive Smart Auto Poster delivery health into one shared Brain risk profile per canonical Telegram chat.

Architecture:

`VM Guard + Posting Intelligence -> Risk Fusion -> canonical opportunity ranking -> later Decision Engine`

The layer is read-only intelligence. It does not become a second governance, posting or execution framework.

## Inputs

### VM Guard

Risk Fusion reads the latest canonical `intelligence.signal.guard_risk_elevated` event per chat from the shared event ledger.

Non-canonical subjects and malformed payloads fail closed and are counted for operator visibility.

### Posting Intelligence

Risk Fusion consumes the passive Posting Intelligence projection, including explicit evidence such as:

- uncertain delivery
- recent posting failures
- destination review requirement
- active quarantine

Raw Smart Auto Poster destination IDs are never exposed. Posting subjects have already been converted to shared canonical IDs.

## Fused risk

The fused score is conservative: it keeps the strongest explicit risk evidence rather than averaging severe evidence away.

Operator levels are:

- `HIGH`: score >= 75
- `MEDIUM`: score >= 45
- `LOW`: score > 0
- `NONE`: no explicit risk evidence

These boundaries are fixed code constants for this milestone. The system does not learn, tune or change them automatically.

## Opportunity integration

`risk_adjusted_canonical_opportunities()` attaches fused risk to the existing canonical Opportunity Engine output.

The original `opportunity_score` remains visible. A separate `risk_adjusted_score` is used as a diagnostic ordering aid.

Importantly, a high-risk opportunity is **not deleted or silently suppressed**. It remains visible with:

- `candidate_visible = true`
- `risk_review_required = true` when applicable
- `automatic_suppression = false`

This preserves evidence and operator control while allowing later Decision Engine work to consume a consistent risk-aware ranking.

## Mission Control

Mission Control exposes:

- Risk Fusion status
- number of fused subjects
- number requiring review
- number at high risk
- fused risk profiles
- risk-adjusted canonical opportunity ranking
- malformed/non-canonical evidence counts

## Safety boundary

Risk Fusion does not:

- create, accept or complete recommendations
- execute Telegram actions
- retry Smart Auto Poster jobs
- mutate queues or destinations
- alter rules or thresholds
- grant external action authority
- automatically suppress candidates

Automatic acceptance, execution, threshold/rule changes and external action authority remain disabled.
