from __future__ import annotations

from .core import add_campaign_content, campaign_preview, create_campaign
from .db import Database, utcnow
from .operations import mark_campaign_previewed, set_campaign_state
from .scheduler import configure_daily, configure_interval, configure_once


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def campaign_wizard(db: Database, timezone_name: str):
    print("SMART AUTO POSTER V3.0 - CAMPAIGN WIZARD")
    print("=" * 72)
    campaign_id = _ask("Campaign ID (no spaces)").lower().replace(" ", "_")
    name = _ask("Campaign name", campaign_id)
    with db.connect() as con:
        contents = con.execute("SELECT content_id,caption FROM content WHERE enabled=1 ORDER BY content_id").fetchall()
    if not contents:
        raise RuntimeError("No enabled content. Import or add content first.")
    print("\nAVAILABLE CONTENT")
    for i, r in enumerate(contents, 1):
        print(f" {i:2}. {r['content_id']}  {(r['caption'] or '').replace(chr(10),' ')[:45]}")
    raw = _ask("Content numbers, comma-separated", "1")
    indexes = []
    for x in raw.split(","):
        try:
            n = int(x.strip())
            if 1 <= n <= len(contents): indexes.append(n - 1)
        except ValueError:
            pass
    if not indexes:
        raise RuntimeError("No valid content selected")
    chosen = [contents[i]["content_id"] for i in dict.fromkeys(indexes)]
    include_tags = _ask("Destination include tags (comma-separated)")
    exclude_tags = _ask("Exclude tags (optional)")
    with db.connect() as con:
        collections = [r[0] for r in con.execute("SELECT collection_id FROM destination_collections WHERE enabled=1 ORDER BY collection_id").fetchall()]
    if collections:
        print("Available collections: " + ", ".join(collections))
    target_collections = _ask("Destination collections (comma-separated, optional)")
    category = _ask("Campaign category (optional)")
    max_cycles = int(_ask("Maximum campaign cycles (0 = unlimited)", "0"))
    priority = int(_ask("Priority 0-100", "50"))
    rotation = _ask("Rotation: sequential/random/least_recent/weighted", "sequential").lower()
    reuse_minutes = int(_ask("Minimum minutes before reusing same variant", "0"))
    conflict_minutes = int(_ask("Minimum queued gap per destination (minutes)", "60"))
    spread_minutes = int(_ask("Spread each campaign run across up to N minutes", "15"))
    protected = _ask("Allow PROTECTED destinations? y/N", "N").lower() in {"y", "yes"}
    create_campaign(
        db, campaign_id, name, chosen[0], priority=priority, tags=include_tags, exclude_tags=exclude_tags,
        rotation_mode=rotation, min_content_reuse_seconds=reuse_minutes * 60,
        allow_protected=protected, conflict_gap_seconds=conflict_minutes * 60, spread_seconds=spread_minutes * 60,
        category=category, target_collections=target_collections, max_cycles=max_cycles,
    )
    for pos, cid in enumerate(chosen):
        add_campaign_content(db, campaign_id, cid, position=pos)

    print("\nSCHEDULE")
    print(" 1. Manual only")
    print(" 2. Every X minutes/hours")
    print(" 3. Specific daily times/days")
    print(" 4. One-off date/time")
    mode = _ask("Choose", "1")
    if mode == "2":
        minutes = float(_ask("Interval minutes", "360"))
        start = float(_ask("First run in minutes", "5"))
        configure_interval(db, campaign_id, int(minutes * 60), timezone_name, start_in_seconds=int(start * 60))
    elif mode == "3":
        times = [x.strip() for x in _ask("Times HH:MM comma-separated", "09:00,18:00").split(",") if x.strip()]
        days_raw = _ask("Days mon,tue,... blank=every day")
        days = [x.strip() for x in days_raw.split(",") if x.strip()] or None
        configure_daily(db, campaign_id, times, days, timezone_name)
    elif mode == "4":
        configure_once(db, campaign_id, _ask("Run at (YYYY-MM-DDTHH:MM)", "2026-08-28T18:00"), timezone_name)

    preview = campaign_preview(db, campaign_id)
    mark_campaign_previewed(db, campaign_id, actor="campaign-wizard")
    print("\nPREVIEW")
    print("=" * 72)
    print(f"Campaign:      {preview['name']} ({campaign_id})")
    print(f"Variants:      {preview['variant_count']} -> {', '.join(preview['variants'])}")
    print(f"Rotation:      {preview['rotation_mode']}")
    print(f"Category:      {preview.get('category') or '-'}")
    print(f"Collections:   {', '.join(preview.get('collections') or []) or '-'}")
    print(f"Cycle limit:   {preview.get('completed_cycles',0)}/{preview.get('max_cycles',0) or 'unlimited'}")
    print(f"Destinations:  {preview['selected']}")
    print(f"Primary only:  {preview['accounts']['primary_only']}")
    print(f"Secondary only:{preview['accounts']['secondary_only']}")
    print(f"Both accounts: {preview['accounts']['both']}")
    print(f"Photo/Text:    {preview['modes'].get('photo',0)}/{preview['modes'].get('text',0)}")
    print(f"Skipped:       {preview['skipped']}")
    confirm = _ask("Enable campaign now? y/N", "N").lower() in {"y", "yes"}
    if confirm:
        set_campaign_state(db, campaign_id, "active", actor="campaign-wizard")
        print(f"[OK] Campaign enabled: {campaign_id}")
    else:
        print(f"[OK] Campaign saved disabled: {campaign_id}")
    return campaign_id
