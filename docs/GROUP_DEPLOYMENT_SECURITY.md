# VM Group Deployment Security Baseline

Status: REQUIRED before a bot is approved for shared-group deployment.

## Security model

Bots may passively observe/index/moderate group traffic where that is their intended function, but group members must not gain a control surface merely because the bot is present in the group.

### Required controls

1. **Owner-bound administration** — administrative actions are authorised by immutable Telegram numeric user ID, never display name or username.
2. **Private-chat control by default** — configuration, health, status, mutation and administrative commands execute only in a private chat with the registered owner/admin.
3. **Private-only first claim** — any bootstrap claim code is accepted only in a private chat, is one-time, and is removed after successful claim.
4. **No group permission oracle** — unauthorised group commands should be ignored rather than exposing administrative state or configuration.
5. **Callback ownership** — inline-button callbacks must repeat the same owner/session authorisation as the originating command.
6. **Fail closed** — missing/invalid owner configuration must disable control functions rather than make them public.
7. **Passive functions separated from control** — monitoring/indexing may continue in groups without allowing group members to invoke privileged operations.
8. **Mutation separation** — destructive or state-changing actions remain separately disabled/confirmed where supported.
9. **Secrets stay local** — tokens, claim codes, admin IDs and session files are local state/environment data and must not be committed.
10. **Automated regression gates** — tests must cover unauthorised group command attempts, private-owner success paths, claim restrictions and callbacks.

## Current bot audit — Stage 1

| Component | Group behaviour | Control status | Stage-1 action |
| --- | --- | --- | --- |
| Admin Command Centre | Administrative only | Admin-ID gated; claim already private-only | Retain and regression-test |
| Smart Auto Poster | Posting worker + admin surface | Existing control/read-only role checks | Audit every callback/mutation path |
| VM Relationship Manager | Passive intelligence + admin UI | Commands and callbacks check configured admin IDs | Retain and regression-test |
| VM Guard | Passive monitoring/moderation | Previously exposed status commands and group claim path | **Hardened: private-owner control only** |
| Universal Search | Passive indexing + search UI | Cross-chat search admin-only, but local group search/help/health remain public | **Next hardening target** |
| VM Ops Control | Private operations surface | Already private-admin gated; private-only claim | Retain and regression-test |

## Deployment gate

A bot is not marked `GROUP_SAFE` until:

- all commands are classified as `PASSIVE_PUBLIC`, `OWNER_PRIVATE`, or `DISABLED`;
- all sensitive commands are `OWNER_PRIVATE`;
- all callback handlers repeat authorisation checks;
- first-admin claim cannot occur in a group;
- unauthorised group tests pass;
- existing bot-specific quality tests pass.
