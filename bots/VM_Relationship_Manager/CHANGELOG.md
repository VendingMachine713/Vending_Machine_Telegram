# VM Relationship Manager Changelog

## Unreleased — Business Memory Product View + Safe Backup

- Added private `/product Product Name` view combining previous clients and suppliers in one read-only product history surface.
- Added product-level deal counts, unique client/supplier counts, quantities, first/last transaction dates and optional recorded AUD history.
- Preserved review-first behavior: product views never send Telegram messages to contacts.
- Replaced raw live-database file copying with SQLite's transactional backup API so WAL-backed Business Memory records are included safely.
- Added tests confirming Business Memory tables and rows survive backup/restore inspection.

## Unreleased — Business Memory Dashboard Integration

- Embedded private Business Memory totals into the main `/rm` relationship dashboard.
- Added repeat-client, repeat-supplier and 30-day reconnect counts to the operator surface.
- Embedded recorded business roles, one-off/repeat pattern, transaction count, products and first/last business dates into private `/person` profiles when business history exists.
- Recorded AUD transaction value is shown only as business history; it is not used as a trust or relationship score.
- Business data remains hidden from non-private admin chats.
- Kept integration additive through a small wrapper layer over the existing Relationship Manager admin bot to reduce regression risk.

## 1.2.0 — Relationship Intelligence + Passive Attention

- Added Relationship Health (0–100), separate from relationship strength and trust.
- Added momentum detection: Learning, Stable, Growing, Surging, Cooling, Fading.
- Added lifecycle intelligence: Discovered, New, Developing, Established, Strong, VIP Candidate, VIP, Cooling, Dormant, Returned.
- Added learned-cycle overdue detection based on each contact's own activity cadence.
- Added smart suggested actions without auto-messaging contacts.
- Added `/today` ranked admin-by-exception inbox.
- Added `/insights`, `/growing`, and `/slipping`.
- Added Intelligence profile button with 7-day vs previous-7-day activity comparison.
- Added passive attention categories for smart follow-up, relationship slipping, critical health and active-unclassified contacts.
- Added daily relationship snapshots for future longer-term trend analysis.
- Dashboard now prioritises Today, Insights, Growing and Slipping.
- Daily/weekly digests now include intelligence and top priorities.
- Intelligence refresh runs locally every 6 hours; database backup remains daily.
- Continues metadata-first privacy: no message-body archive is introduced.
- Existing `.env`, Telegram session and relationship database are not included in this direct update.
