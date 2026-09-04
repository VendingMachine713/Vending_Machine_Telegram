# VM Relationship Manager Changelog

## Unreleased — Low-Touch Business Capture

- Added business action buttons directly to every private contact profile: `+ Client deal` and `+ Supplier deal`.
- Added contact-aware product suggestions so repeated products can be recorded with one tap.
- Added recent global product fallback so newly classified contacts can reuse existing product identities without typing them again.
- Added first-product/new-product capture by sending the product name as the next message after choosing the client/supplier role.
- Added a five-minute pending-capture expiry and explicit Cancel control so ordinary contact search resumes automatically.
- Added `Repeat last business deal` for contacts with history; the shortcut repeats role/product/quantity/unit but deliberately does not copy an old monetary value.
- Quick capture records one unit and no inferred transaction value unless the operator uses the existing full `/deal` command for detailed quantity/value/note entry.
- Existing contact IDs are reused automatically; normal business recording no longer requires CSV editing or manual Telegram-ID lookup.
- CSV import remains available only for genuine bulk historical migration/recovery work.

## Unreleased — Passive Business Intelligence

- Added explicit private `/available Product Name` and `/unavailable Product Name` status controls for products already known to Business Memory.
- Added a private Business Memory action section to `/today` with available-product, reload-candidate, dormant-client and repeat-dormant counts plus a small ranked preview.
- Added passive reload-opportunity and dormant-client projections without sending messages to any contact.
- Added a read-only VM Brain adapter that maps Business Memory into aggregate chat-level signals without copying notes, message bodies, usernames, display names, raw Telegram contact IDs or product names.
- Extended the canonical Trust Layer bridge for `business_reload_opportunity` and `business_dormant_client_opportunity` signals.
- Canonical Business Memory integration remains signal-only: it creates no recommendation, approval or execution authority.

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
