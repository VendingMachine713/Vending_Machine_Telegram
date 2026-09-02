# VM Brain Phase 2 — Make Brain Useful

Phase 2 advances VM Core from the passive v2.0 trust layer to a practical v2.4 operator intelligence surface.

## v2.1 — Mission Control

Module: `shared.vm_core.mission_control`

Mission Control provides one passive snapshot covering:

- service runtime counts
- open incidents and severity
- active signals
- ranked decisions
- opportunities and blocked opportunities
- rule-health rollback recommendations
- conflicts requiring human resolution
- entity/relationship counts

It does not accept recommendations or execute actions.

## v2.2 — Entity and Context Graph

Module: `shared.vm_core.entity_graph`

The graph unifies shared metadata for destinations, accounts, incidents, signals, recommendations and referenced campaign/account context.

Privacy boundaries:

- no Telegram message bodies are copied
- no bot-owned databases are written
- only shared operational metadata and derived evidence are used

## v2.3 — Opportunity Intelligence

Module: `shared.vm_core.opportunity_intelligence`

Opportunity Intelligence aggregates evidence by subject and combines:

- positive relationship/campaign signals
- confidence
- delivery risk
- active incidents

ERROR/CRITICAL subject incidents block an opportunity from being treated as immediately actionable. Delivery-risk signals reduce opportunity score.

## v2.4 — Smart Auto Poster Intelligence Integration

Module: `shared.vm_core.autoposter_intelligence`

The SAP bridge reuses the existing read-only Smart Auto Poster adapter and may create or refresh only `PROPOSED` review recommendations in shared VM Core state.

It never:

- sends Telegram messages
- mutates SAP queues
- retries uncertain jobs
- writes SAP-owned tables
- accepts its own recommendations
- executes external actions

## Operator view

```powershell
python tools/vm_brain_phase2.py mission
python tools/vm_brain_phase2.py graph
python tools/vm_brain_phase2.py opportunities --limit 20
python tools/vm_brain_phase2.py sap-sync --limit 20
```

`sap-sync` refreshes shared evidence from SAP read-only sources and creates passive review recommendations only.

## Phase 2 progression

`Trusted Decisions -> Mission Control -> Entity Graph -> Opportunity Intelligence -> Passive SAP Intelligence`

The next phase can focus on richer learning loops, cross-bot opportunity correlation, operator notifications by exception and controlled action proposals without weakening the human-governed execution boundary.
