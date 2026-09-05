# Vending Machine Telegram

Permanent master project for all Vending Machine Telegram bots, tools, shared runtime data, documentation and archived material.

## Operator start point

Run `START_HERE.ps1` from the repository root.

The launcher now exposes:

- `M` — Mission Control operator home: compact health, attention, intelligence and governance summary.
- `A` — Group Member Audit: passive group composition, classification confidence, attention and audit history.
- `G` — Operator Guide: plain-English explanation of how to run and navigate the system.
- `1-9` — existing bot, tool and folder launch options.

For normal operation, start with **Mission Control**. Open individual bot folders only when investigating or performing a bot-specific task.

See `docs/OPERATOR_GUIDE.md` for the complete operating flow.

## Rule

Use one permanent folder per bot or tool. Update that folder in place. Do not create parallel `new`, `final`, `final2`, or version-suffixed project trees.

## Current bot locations

- `bots/Smart_Auto_Poster_V2/`
- `bots/VM_Guard/`
- `bots/Universal_Search/`
- `bots/Admin_Command_Centre/`
- `bots/VM_Relationship_Manager/`

Mission Control remains read-only. Automatic acceptance, automatic execution, and external action authority remain disabled unless separately governed and enabled in a future milestone.
