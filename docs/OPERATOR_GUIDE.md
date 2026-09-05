# VM Operator Guide

Updated: 2026-09-05

This guide is the normal operating path for the Vending Machine Telegram system. The aim is to operate from one high-level surface and only open individual bots when something needs investigation.

## 1. Normal start

1. Open the repository root.
2. Run `START_HERE.ps1`.
3. Press `M` for **Mission Control - operator home**.
4. Read the top-level `SYSTEM` state.
5. If the state is `HEALTHY`, no routine intervention is required.
6. If the state is `ATTENTION`, read the `ATTENTION REQUIRED` section before opening any individual bot.

Mission Control is read-only. Opening it does not send Telegram messages, start campaigns, accept recommendations, or grant VM Brain external action authority.

## 2. What the Mission Control home means

### SYSTEM HEALTH

This answers: **Is the platform operating normally?**

- **Registered services** — services known to the VM Platform registry.
- **Running services observed** — services currently represented by runtime telemetry.
- **Unhealthy services** — services whose health contract reports a problem.
- **Services not ready** — services known to the platform but not currently ready for work.
- **Open incidents** — unresolved platform or bot incidents.
- **Heartbeat incident candidates** — missing, stale, or abnormal heartbeat evidence that may need investigation.

### ATTENTION REQUIRED

This answers: **Do I need to do anything?**

It is intentionally exception-first. Items can include:

- unhealthy or not-ready services;
- open incidents;
- stale or abnormal telemetry;
- heartbeat failures;
- risk subjects requiring operator review;
- posting destinations requiring review;
- completed Brain reviews still waiting for verified outcome evidence.

If this section says nothing requires attention, do not open individual bot logs just to check them.

### INTELLIGENCE

This answers: **What is the system learning or noticing?**

- **Opportunities** — current candidate opportunities detected by the intelligence layer.
- **Canonical opportunities** — opportunities supported by the governed canonical path.
- **Ranked decisions** — read-only Brain decision candidates.
- **Relationship profiles** — contacts currently represented in relationship intelligence.
- **Cooling relationships** — relationships whose recent activity is declining.
- **Dormant relationships** — previously active relationships now inactive.
- **Group activity profiles** — Telegram group/search activity represented in the intelligence layer.

These are intelligence summaries, not automatic instructions to act.

### BRAIN / GOVERNANCE

This answers: **Can I trust the current Brain evidence path?**

- **Canonical readiness** — whether the governed canonical intelligence path is ready.
- **Evidence health** — whether evidence is sufficiently fresh and valid.
- **Review calibration** — whether reviewed recommendations and outcomes remain acceptably calibrated.
- **Audit status** — whether the canonical review audit timeline is healthy and readable.

### SAFETY BOUNDARY

This answers: **What authority does the system currently have?**

The operator home displays whether these are enabled:

- automatic acceptance;
- automatic execution;
- external action authority.

The current intended state is **OFF / OFF / OFF**.

## 3. What each service does

### VM Platform

Shared infrastructure underneath the bots.

Responsibilities include:

- service registry;
- health contracts;
- telemetry and heartbeats;
- incidents;
- shared paths/configuration;
- aggregation for Mission Control;
- shared intelligence/event foundations.

Normally, you do not operate this directly.

### VM Brain

The shared intelligence and recommendation layer.

It combines governed evidence from other services into:

- opportunities;
- risk-aware ranking;
- predictions;
- decisions;
- recommendations;
- review history;
- verified outcomes;
- learning/calibration.

It remains advisory unless future capability gates explicitly grant narrow authority.

### Smart Auto Poster

Handles posting workflow and posting-related telemetry/intelligence.

Use it when investigating:

- routes/destinations;
- posting workflow;
- campaign state;
- delivery evidence;
- uncertain or quarantined posting work.

### Universal Search

Handles Telegram search and marketplace/group intelligence.

Use it when investigating:

- group/search activity;
- demand/supply matching;
- search coverage;
- marketplace intelligence.

### VM Relationship Manager

Builds relationship and business-memory intelligence.

Use it when investigating:

- contact profiles;
- activity history;
- relationship state;
- corrections/imports;
- cooling or dormant relationships.

### VM Guard

Security and risk observer.

Use it when investigating:

- security signals;
- abnormal activity;
- risk evidence;
- Guard-specific incidents.

### Admin Command Centre

Telegram-facing operator control surface.

Use it for explicitly supported manual admin workflows. It should remain the sole Telegram admin owner where the architecture requires one owner.

## 4. Normal daily use

Your normal workflow should be:

`START_HERE.ps1 -> M -> read SYSTEM -> read ATTENTION REQUIRED -> act only if needed`

You should not routinely:

- open five separate bot consoles;
- read raw logs without an incident;
- manually compare databases;
- manually infer whether services are healthy;
- assume a recommendation has been executed.

## 5. When Mission Control shows ATTENTION

Use this order:

1. Read the attention item.
2. Identify the named service or intelligence area.
3. Open only that service or the relevant maintenance tool.
4. Check the linked health/incident evidence.
5. Avoid manual retries of uncertain Telegram/posting work unless the workflow explicitly supports them.
6. After recovery or correction, reopen Mission Control and confirm the attention item has cleared.

## 6. When to use full Mission Control JSON

The human-readable home is for normal operation.

Use:

`py tools\vm_brain_phase2.py mission`

only when you need detailed evidence such as:

- service-level telemetry;
- full incident aggregation;
- canonical recommendation details;
- risk-adjusted opportunities;
- decision details;
- prediction detail;
- audit timelines;
- relationship/search/posting evidence.

## 7. Current operational boundary

A green Mission Control screen means the **recorded VM Platform state** is healthy. It is not proof that an external Telegram action succeeded unless delivery evidence exists.

The system deliberately does not treat missing delivery evidence as success.

Current safety policy remains:

- no automatic acceptance;
- no automatic external execution;
- no automatic threshold/rule/trust changes;
- no automatic conflict resolution;
- uncertain work remains fail-closed.

## 8. Source-of-truth rule

GitHub `main` is the development source of truth after a milestone is merged green.

The Windows runtime is the deployment/runtime source until the live cutover for that merged milestone is explicitly verified.

Do not assume a GitHub merge automatically means the live Windows processes were updated or restarted.
