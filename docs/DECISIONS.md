# Architecture Decision Log

## ADR-001 — Modular bots + shared core
Status: Accepted

Keep bot failure domains independent while progressively extracting reusable infrastructure into VM Core.

## ADR-002 — Telethon for existing MTProto/user-account work
Status: Accepted

Preserve the established Telethon-based flows. Do not migrate working account/session logic merely for framework consistency.

## ADR-003 — Dry-run first
Status: Accepted

Start/stop/rollback/dependency changes require an explicit apply flag from the CLI.

## ADR-004 — No secrets in diagnostics
Status: Accepted

Support bundles and structure reports exclude `.env`, Telegram session contents, private media, and databases.
