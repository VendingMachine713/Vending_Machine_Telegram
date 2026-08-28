# VM Relationship Manager Changelog

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
