from __future__ import annotations

from . import __version__
import re

from .core import ROTATION_MODES, add_campaign_content, campaign_preview, create_campaign
from .db import Database
from .operations import mark_campaign_previewed, set_campaign_state
from .scheduler import configure_daily, configure_interval, configure_once


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def _ask_choice(prompt: str, choices: set[str], default: str, aliases: dict[str, str] | None = None) -> str:
    aliases = {k.lower(): v.lower() for k, v in (aliases or {}).items()}
    normalized = {x.lower() for x in choices}
    while True:
        raw = _ask(prompt, default).strip().lower()
        # Be forgiving when a user pastes a displayed label like "Mode: any".
        if ":" in raw:
            raw = raw.rsplit(":", 1)[-1].strip()
        raw = aliases.get(raw, raw)
        if raw in normalized:
            return raw
        print(f"[INPUT] Choose one of: {', '.join(sorted(normalized))}")


def _ask_int(prompt: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("[INPUT] Enter a whole number.")
            continue
        if minimum is not None and value < minimum:
            print(f"[INPUT] Minimum is {minimum}.")
            continue
        if maximum is not None and value > maximum:
            print(f"[INPUT] Maximum is {maximum}.")
            continue
        return value


def _ask_float(prompt: str, default: float, *, minimum: float | None = None) -> float:
    while True:
        raw = _ask(prompt, str(default).rstrip("0").rstrip(".") if isinstance(default, float) else str(default))
        try:
            value = float(raw)
        except ValueError:
            print("[INPUT] Enter a number.")
            continue
        if minimum is not None and value < minimum:
            print(f"[INPUT] Minimum is {minimum}.")
            continue
        return value


def _parse_content_selection(raw: str, contents) -> list[str]:
    by_id = {str(r["content_id"]).lower(): str(r["content_id"]) for r in contents}
    chosen: list[str] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            n = int(value)
        except ValueError:
            cid = by_id.get(value.lower())
            if cid:
                chosen.append(cid)
            continue
        if 1 <= n <= len(contents):
            chosen.append(str(contents[n - 1]["content_id"]))
    return list(dict.fromkeys(chosen))


def campaign_wizard(db: Database, timezone_name: str):
    print(f"SMART AUTO POSTER V{__version__} - CAMPAIGN WIZARD")
    print("=" * 72)

    campaign_id = _ask("Campaign ID (no spaces)").lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", campaign_id or ""):
        raise RuntimeError("Campaign ID must contain only letters, numbers, underscores or hyphens")

    with db.connect() as con:
        existing = con.execute("SELECT name FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
    if existing:
        confirm = _ask(f"Campaign {campaign_id} already exists. Update it? y/N", "N").lower()
        if confirm not in {"y", "yes"}:
            print("[OK] Wizard cancelled; existing campaign unchanged")
            return campaign_id

    name = _ask("Campaign name", existing["name"] if existing else campaign_id)

    with db.connect() as con:
        contents = con.execute(
            "SELECT content_id,caption FROM content WHERE enabled=1 ORDER BY content_id"
        ).fetchall()
    if not contents:
        raise RuntimeError("No enabled content. Import or add content first.")

    print("\nAVAILABLE CONTENT")
    for i, r in enumerate(contents, 1):
        print(f" {i:2}. {r['content_id']}  {(r['caption'] or '').replace(chr(10),' ')[:45]}")

    while True:
        raw = _ask("Content numbers or IDs, comma-separated", "1")
        chosen = _parse_content_selection(raw, contents)
        if chosen:
            break
        print("[INPUT] No valid content selected. Use numbers or exact content IDs from the list above.")

    with db.connect() as con:
        collection_rows = con.execute(
            "SELECT collection_id FROM destination_collections WHERE enabled=1 ORDER BY collection_id"
        ).fetchall()
        collections = [str(r[0]) for r in collection_rows]
        has_live_test = bool(
            con.execute("SELECT 1 FROM destination_tags WHERE tag='live_test' LIMIT 1").fetchone()
        )

    include_tags = _ask("Destination include tags (comma-separated)")
    exclude_default = "live_test" if has_live_test else ""
    exclude_tags = _ask("Exclude tags (optional)", exclude_default)

    default_collection = "all_approved" if "all_approved" in collections else ""
    if collections:
        print("Available collections: " + ", ".join(collections))
    target_collections = _ask("Destination collections (comma-separated, optional)", default_collection)

    unknown_collections = [
        x.strip().lower() for x in target_collections.split(",")
        if x.strip() and x.strip().lower() not in {c.lower() for c in collections}
    ]
    if unknown_collections:
        raise RuntimeError("Unknown destination collection(s): " + ", ".join(unknown_collections))

    category = _ask("Campaign category (optional)")
    max_cycles = _ask_int("Maximum campaign cycles (0 = unlimited)", 0, minimum=0)
    priority = _ask_int("Priority 0-100", 50, minimum=0, maximum=100)
    rotation = _ask_choice(
        "Rotation: sequential/random/least_recent/weighted",
        ROTATION_MODES,
        "least_recent" if len(chosen) > 1 else "sequential",
        aliases={"lru": "least_recent", "least-recent": "least_recent", "least recent": "least_recent"},
    )
    reuse_minutes = _ask_int("Minimum minutes before reusing same variant", 0, minimum=0)
    conflict_minutes = _ask_int("Minimum queued gap per destination (minutes)", 60, minimum=0)
    spread_minutes = _ask_int("Spread each campaign run across up to N minutes", 15, minimum=0)
    protected = _ask("Allow PROTECTED destinations? y/N", "N").lower() in {"y", "yes"}

    print("\nCONFIGURATION SUMMARY")
    print("=" * 72)
    print(f"Campaign:       {campaign_id} | {name}")
    print(f"Content:        {', '.join(chosen)}")
    print(f"Collections:    {target_collections or '-'}")
    print(f"Include tags:   {include_tags or '-'}")
    print(f"Exclude tags:   {exclude_tags or '-'}")
    print(f"Rotation:       {rotation}")
    print(f"Priority:       {priority}")
    print(f"Reuse minutes:  {reuse_minutes}")
    print(f"Conflict gap:   {conflict_minutes} min")
    print(f"Spread:         {spread_minutes} min")
    print(f"Protected:      {'YES' if protected else 'NO'}")

    create_campaign(
        db,
        campaign_id,
        name,
        chosen[0],
        priority=priority,
        tags=include_tags,
        exclude_tags=exclude_tags,
        rotation_mode=rotation,
        min_content_reuse_seconds=reuse_minutes * 60,
        allow_protected=protected,
        conflict_gap_seconds=conflict_minutes * 60,
        spread_seconds=spread_minutes * 60,
        category=category,
        target_collections=target_collections,
        max_cycles=max_cycles,
    )

    # Make reruns idempotent: exactly the selected variants stay enabled.
    with db.connect() as con:
        if chosen:
            placeholders = ",".join("?" for _ in chosen)
            con.execute(
                f"UPDATE campaign_content SET enabled=0 WHERE campaign_id=? AND content_id NOT IN ({placeholders})",
                [campaign_id, *chosen],
            )
    for pos, cid in enumerate(chosen):
        add_campaign_content(db, campaign_id, cid, position=pos, enabled=True)

    print("\nSCHEDULE")
    print(" 1. Manual only")
    print(" 2. Every X minutes/hours")
    print(" 3. Specific daily times/days")
    print(" 4. One-off date/time")
    mode = _ask_choice("Choose", {"1", "2", "3", "4"}, "1")
    if mode == "2":
        minutes = _ask_float("Interval minutes", 360.0, minimum=1.0)
        start = _ask_float("First run in minutes", 5.0, minimum=0.0)
        configure_interval(db, campaign_id, int(minutes * 60), timezone_name, start_in_seconds=int(start * 60))
    elif mode == "3":
        times = [x.strip() for x in _ask("Times HH:MM comma-separated", "09:00,18:00").split(",") if x.strip()]
        days_raw = _ask("Days mon,tue,... blank=every day")
        days = [x.strip() for x in days_raw.split(",") if x.strip()] or None
        configure_daily(db, campaign_id, times, days, timezone_name)
    elif mode == "4":
        configure_once(db, campaign_id, _ask("Run at (YYYY-MM-DDTHH:MM)"), timezone_name)

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
        print(f"[OK] Campaign saved READY but inactive: {campaign_id}")
    return campaign_id
