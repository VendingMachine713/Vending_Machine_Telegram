from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database, utcnow
from .time_rules import parse_hhmm

ROTATION_MODES = {"sequential", "random", "least_recent", "weighted"}
SYSTEM_TAG_PREFIX = "auto_"


def _csv_tags(value: str | None) -> set[str]:
    return {x.strip().lower() for x in (value or "").split(",") if x.strip()}


def content_fingerprint(caption: str, media: list[str]) -> str:
    h = hashlib.sha256()
    h.update((caption or "").encode("utf-8", "ignore"))
    for raw in media:
        p = Path(raw)
        h.update(p.name.encode("utf-8", "ignore"))
        h.update(str(p.stat().st_size).encode())
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def create_content(db: Database, content_id: str, caption: str, media: list[str], source_dir: str | None = None,
                   fingerprint: str | None = None):
    content_id = content_id.strip()
    if not content_id:
        raise ValueError("content_id cannot be empty")
    missing = [p for p in media if not Path(p).exists()]
    if missing:
        raise FileNotFoundError("Missing media: " + ", ".join(missing))
    fp = fingerprint or content_fingerprint(caption, media)
    now = utcnow()
    with db.connect() as con:
        dup = con.execute("SELECT content_id FROM content WHERE fingerprint=? AND content_id<>?", (fp, content_id)).fetchone()
        if dup:
            raise RuntimeError(f"Duplicate content fingerprint already registered as: {dup['content_id']}")
        con.execute('''INSERT INTO content(content_id,caption,media_json,source_dir,fingerprint,lifecycle_state,enabled,created_at,updated_at)
                       VALUES(?,?,?,?,?,'ready',1,?,?) ON CONFLICT(content_id) DO UPDATE SET caption=excluded.caption,
                       media_json=excluded.media_json,source_dir=COALESCE(excluded.source_dir,content.source_dir),
                       fingerprint=excluded.fingerprint,lifecycle_state='ready',enabled=1,updated_at=excluded.updated_at''',
                    (content_id, caption, json.dumps(media, ensure_ascii=False), source_dir, fp, now, now))


def create_campaign(db: Database, campaign_id: str, name: str, content_id: str, priority=50, tags="",
                    start_at: str | None = None, end_at: str | None = None,
                    min_destination_interval_seconds: int = 0, *, exclude_tags: str = "",
                    rotation_mode: str = "sequential", min_content_reuse_seconds: int = 0,
                    allow_protected: bool = False, conflict_gap_seconds: int = 0, spread_seconds: int = 0,
                    category: str = '', target_collections: str = '', max_cycles: int = 0):
    now = utcnow()
    campaign_id = campaign_id.strip()
    rotation_mode = rotation_mode.strip().lower()
    if not campaign_id:
        raise ValueError("campaign_id cannot be empty")
    if not (0 <= int(priority) <= 100):
        raise ValueError("priority must be between 0 and 100")
    if int(min_destination_interval_seconds) < 0:
        raise ValueError("min_destination_interval_seconds cannot be negative")
    if int(min_content_reuse_seconds) < 0:
        raise ValueError("min_content_reuse_seconds cannot be negative")
    if int(conflict_gap_seconds) < 0:
        raise ValueError("conflict_gap_seconds cannot be negative")
    if int(spread_seconds) < 0:
        raise ValueError("spread_seconds cannot be negative")
    if int(max_cycles) < 0:
        raise ValueError("max_cycles cannot be negative")
    if rotation_mode not in ROTATION_MODES:
        raise ValueError(f"rotation_mode must be one of: {', '.join(sorted(ROTATION_MODES))}")
    if start_at and end_at and start_at >= end_at:
        raise ValueError("campaign start_at must be before end_at")
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM content WHERE content_id=?", (content_id,)).fetchone():
            raise RuntimeError(f"Unknown content_id: {content_id}")
        existing = con.execute("SELECT enabled,lifecycle_state FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        enabled = int(existing["enabled"]) if existing else 0
        lifecycle_state = existing["lifecycle_state"] if existing else 'draft'
        con.execute('''INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,target_tags,exclude_tags,
                       rotation_mode,min_content_reuse_seconds,allow_protected,conflict_gap_seconds,spread_seconds,start_at,end_at,
                       min_destination_interval_seconds,category,target_collections,max_cycles,completed_cycles,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
                       ON CONFLICT(campaign_id) DO UPDATE SET name=excluded.name,content_id=excluded.content_id,
                       priority=excluded.priority,target_tags=excluded.target_tags,exclude_tags=excluded.exclude_tags,
                       rotation_mode=excluded.rotation_mode,min_content_reuse_seconds=excluded.min_content_reuse_seconds,
                       allow_protected=excluded.allow_protected,conflict_gap_seconds=excluded.conflict_gap_seconds,spread_seconds=excluded.spread_seconds,
                       start_at=excluded.start_at,end_at=excluded.end_at,
                       min_destination_interval_seconds=excluded.min_destination_interval_seconds,category=excluded.category,
                       target_collections=excluded.target_collections,max_cycles=excluded.max_cycles,updated_at=excluded.updated_at''',
                    (campaign_id, name, content_id, enabled, lifecycle_state, int(priority), tags, exclude_tags, rotation_mode,
                     int(min_content_reuse_seconds), int(bool(allow_protected)), int(conflict_gap_seconds), int(spread_seconds), start_at, end_at,
                     int(min_destination_interval_seconds), category.strip(), ','.join(sorted(_csv_tags(target_collections))), int(max_cycles), now, now))
        con.execute('''INSERT OR IGNORE INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at)
                       VALUES(?,?,0,1,1,?)''', (campaign_id, content_id, now))


def add_campaign_content(db: Database, campaign_id: str, content_id: str, *, position: int | None = None,
                         weight: int = 1, enabled: bool = True):
    if int(weight) < 1:
        raise ValueError("weight must be >= 1")
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        if not con.execute("SELECT 1 FROM content WHERE content_id=?", (content_id,)).fetchone():
            raise RuntimeError(f"Unknown content: {content_id}")
        if position is None:
            row = con.execute("SELECT COALESCE(MAX(position),-1)+1 FROM campaign_content WHERE campaign_id=?", (campaign_id,)).fetchone()
            position = int(row[0])
        con.execute('''INSERT INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(campaign_id,content_id) DO UPDATE SET
                       position=excluded.position,weight=excluded.weight,enabled=excluded.enabled''',
                    (campaign_id, content_id, int(position), int(weight), int(bool(enabled)), utcnow()))


def remove_campaign_content(db: Database, campaign_id: str, content_id: str):
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM campaign_content WHERE campaign_id=? AND enabled=1", (campaign_id,)).fetchone()[0]
        if count <= 1:
            raise RuntimeError("A campaign must keep at least one enabled content item")
        con.execute("UPDATE campaign_content SET enabled=0 WHERE campaign_id=? AND content_id=?", (campaign_id, content_id))


def clone_campaign(db: Database, source_id: str, new_id: str, new_name: str | None = None):
    now = utcnow()
    with db.connect() as con:
        src = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (source_id,)).fetchone()
        if not src:
            raise RuntimeError(f"Unknown campaign: {source_id}")
        if con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (new_id,)).fetchone():
            raise RuntimeError(f"Campaign already exists: {new_id}")
        cols = [r[1] for r in con.execute("PRAGMA table_info(campaigns)").fetchall()]
        data = dict(src)
        data["campaign_id"] = new_id
        data["name"] = new_name or f"{src['name']} Copy"
        data["enabled"] = 0
        if "lifecycle_state" in data: data["lifecycle_state"] = "draft"
        if "last_preview_at" in data: data["last_preview_at"] = None
        data["created_at"] = now
        data["updated_at"] = now
        con.execute(f"INSERT INTO campaigns({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", [data[c] for c in cols])
        rows = con.execute("SELECT content_id,position,weight,enabled FROM campaign_content WHERE campaign_id=?", (source_id,)).fetchall()
        for r in rows:
            con.execute("INSERT INTO campaign_content(campaign_id,content_id,position,weight,enabled,added_at) VALUES(?,?,?,?,?,?)",
                        (new_id, r["content_id"], r["position"], r["weight"], r["enabled"], now))
        sched = con.execute("SELECT * FROM campaign_schedules WHERE campaign_id=?", (source_id,)).fetchone()
        if sched:
            # Clone schedule settings but leave it disabled and recalculate only when explicitly enabled/configured.
            con.execute('''INSERT INTO campaign_schedules(campaign_id,mode,interval_seconds,daily_times_json,days_json,timezone,
                           next_run_at,last_run_at,jitter_seconds,enabled,updated_at) VALUES(?,?,?,?,?,?,?,?,?,0,?)''',
                        (new_id, sched["mode"], sched["interval_seconds"], sched["daily_times_json"], sched["days_json"],
                         sched["timezone"], None, None, sched["jitter_seconds"], now))
    return new_id


def _campaign_active(camp, now: str):
    if camp["start_at"] and now < camp["start_at"]:
        return False, f"Campaign has not started yet: {camp['start_at']}"
    if camp["end_at"] and now > camp["end_at"]:
        return False, f"Campaign has ended: {camp['end_at']}"
    return True, None


def _campaign_content_rows(con, campaign_id: str):
    return con.execute('''SELECT cc.content_id,cc.position,cc.weight,cc.enabled,ct.enabled AS content_enabled,
                          ct.caption,ct.media_json
                          FROM campaign_content cc JOIN content ct ON ct.content_id=cc.content_id
                          WHERE cc.campaign_id=? AND cc.enabled=1 AND ct.enabled=1
                          ORDER BY cc.position,cc.content_id''', (campaign_id,)).fetchall()


def _select_content(con, camp, group_id: int):
    rows = _campaign_content_rows(con, camp["campaign_id"])
    if not rows:
        raise RuntimeError(f"Campaign has no enabled content variants: {camp['campaign_id']}")
    if len(rows) == 1:
        return rows[0]["content_id"]

    now = datetime.now(timezone.utc)
    state = con.execute("SELECT last_content_id,last_used_at FROM campaign_destination_state WHERE campaign_id=? AND group_id=?",
                        (camp["campaign_id"], group_id)).fetchone()
    last_content = state["last_content_id"] if state else None
    # Also consider the newest queued job, preventing repeated variants before prior jobs have sent.
    qlast = con.execute('''SELECT content_id FROM queue WHERE campaign_id=? AND group_id=? AND content_id IS NOT NULL
                           AND status NOT IN ('cancelled','failed') ORDER BY id DESC LIMIT 1''',
                        (camp["campaign_id"], group_id)).fetchone()
    if qlast:
        last_content = qlast["content_id"]

    reuse_seconds = int(camp["min_content_reuse_seconds"] or 0)
    candidates = []
    for row in rows:
        usage = con.execute("SELECT last_used_at,use_count FROM content_usage WHERE campaign_id=? AND group_id=? AND content_id=?",
                            (camp["campaign_id"], group_id, row["content_id"])).fetchone()
        last_used = None
        use_count = 0
        if usage:
            use_count = int(usage["use_count"] or 0)
            if usage["last_used_at"]:
                try:
                    last_used = datetime.fromisoformat(usage["last_used_at"])
                    if last_used.tzinfo is None:
                        last_used = last_used.replace(tzinfo=timezone.utc)
                except Exception:
                    last_used = None
        too_recent = bool(reuse_seconds and last_used and last_used + timedelta(seconds=reuse_seconds) > now)
        candidates.append({"row": row, "last_used": last_used, "use_count": use_count, "too_recent": too_recent})

    allowed = [x for x in candidates if not x["too_recent"] and x["row"]["content_id"] != last_content]
    if not allowed:
        allowed = [x for x in candidates if x["row"]["content_id"] != last_content]
    if not allowed:
        allowed = candidates

    mode = (camp["rotation_mode"] or "sequential").lower()
    if mode == "random":
        return random.choice(allowed)["row"]["content_id"]
    if mode == "weighted":
        weights = [max(1, int(x["row"]["weight"] or 1)) for x in allowed]
        return random.choices(allowed, weights=weights, k=1)[0]["row"]["content_id"]
    if mode == "least_recent":
        def key(x):
            stamp = x["last_used"] or datetime.min.replace(tzinfo=timezone.utc)
            return (stamp, x["use_count"], int(x["row"]["position"]))
        return min(allowed, key=key)["row"]["content_id"]
    # sequential: choose the first position after the last queued/sent variant, wrapping around.
    ordered = sorted(allowed, key=lambda x: (int(x["row"]["position"]), x["row"]["content_id"]))
    full = [x["row"]["content_id"] for x in sorted(candidates, key=lambda x: (int(x["row"]["position"]), x["row"]["content_id"]))]
    if last_content in full:
        start = (full.index(last_content) + 1) % len(full)
        for offset in range(len(full)):
            wanted = full[(start + offset) % len(full)]
            for x in allowed:
                if x["row"]["content_id"] == wanted:
                    return wanted
    return ordered[0]["row"]["content_id"]


def _eligible_destinations(con, camp):
    from .collections import destination_matches_collection

    include_tags = _csv_tags(camp["target_tags"])
    exclude_tags = _csv_tags(camp["exclude_tags"])
    collection_ids = _csv_tags(camp["target_collections"]) if "target_collections" in camp.keys() else set()
    collections = []
    for cid in sorted(collection_ids):
        row = con.execute("SELECT * FROM destination_collections WHERE collection_id=? AND enabled=1", (cid,)).fetchone()
        if row:
            collections.append(dict(row))
    dests = con.execute("SELECT * FROM destinations WHERE enabled=1 AND needs_review=0 AND mode IN ('photo','text') ORDER BY group_name").fetchall()
    selected, skipped = [], {"no_access": 0, "never_auto_post": 0, "protected": 0, "include_tags": 0, "exclude_tags": 0, "collections": 0}
    for d in dests:
        if not (d["primary_access"] or d["secondary_access"]):
            skipped["no_access"] += 1; continue
        if d["never_auto_post"]:
            skipped["never_auto_post"] += 1; continue
        dtags = {r[0].lower() for r in con.execute("SELECT tag FROM destination_tags WHERE group_id=?", (d["group_id"],)).fetchall()}
        direct_match = (not include_tags) or bool(include_tags.intersection(dtags))
        collection_match = any(destination_matches_collection(dict(d), dtags, c) for c in collections)
        if collection_ids:
            # Direct tags and collections are a union; with only collections configured, at least one must match.
            if include_tags:
                target_match = direct_match or collection_match
            else:
                target_match = collection_match
        else:
            target_match = direct_match
        if not target_match:
            if collection_ids and not include_tags: skipped["collections"] += 1
            else: skipped["include_tags"] += 1
            continue
        if exclude_tags and exclude_tags.intersection(dtags):
            skipped["exclude_tags"] += 1; continue
        # Campaign protected override still applies when selected directly. Collections may explicitly include protected.
        collection_allows_protected = collection_match and any(c.get("include_protected") for c in collections if destination_matches_collection(dict(d), dtags, c))
        if d["protected"] and not camp["allow_protected"] and not collection_allows_protected:
            skipped["protected"] += 1; continue
        selected.append(d)
    return selected, skipped


def _next_due(con, d, camp, base_iso: str, salt: str = ""):
    base = datetime.fromisoformat(base_iso)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    spacing = max(int(d["min_interval_seconds"] or 0), int(camp["min_destination_interval_seconds"] or 0),
                  int(camp["conflict_gap_seconds"] or 0))
    row = con.execute('''SELECT due_at FROM queue WHERE group_id=? AND status IN ('pending','retry','sending','deferred')
                         ORDER BY due_at DESC,id DESC LIMIT 1''', (d["group_id"],)).fetchone()
    if row and spacing > 0:
        try:
            latest = datetime.fromisoformat(row["due_at"])
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            base = max(base, latest + timedelta(seconds=spacing))
        except Exception:
            pass
    if d["next_eligible_at"]:
        try:
            eligible = datetime.fromisoformat(d["next_eligible_at"])
            if eligible.tzinfo is None:
                eligible = eligible.replace(tzinfo=timezone.utc)
            base = max(base, eligible)
        except Exception:
            pass
    # Optional cross-campaign minimum-gap rules for the same destination.
    relations = con.execute("SELECT related_campaign_id,min_gap_seconds FROM campaign_relations WHERE campaign_id=? AND relation_type='min_gap'", (camp["campaign_id"],)).fetchall()
    for rel in relations:
        gap = max(0, int(rel["min_gap_seconds"] or 0))
        if not gap:
            continue
        other = con.execute("""SELECT status,due_at,updated_at FROM queue WHERE group_id=? AND campaign_id=?
                               AND status NOT IN ('cancelled','expired') ORDER BY id DESC LIMIT 1""",
                            (d["group_id"], rel["related_campaign_id"])).fetchone()
        if other:
            raw = other["updated_at"] if other["status"] == "sent" else other["due_at"]
            try:
                anchor = datetime.fromisoformat(raw)
                if anchor.tzinfo is None: anchor = anchor.replace(tzinfo=timezone.utc)
                base = max(base, anchor + timedelta(seconds=gap))
            except Exception:
                pass
    spread = max(0, int(camp["spread_seconds"] or 0)) if "spread_seconds" in camp.keys() else 0
    if spread:
        seed = hashlib.sha256(f"{d['group_id']}|{salt}".encode()).hexdigest()
        offset = int(seed[:8], 16) % (spread + 1)
        base += timedelta(seconds=offset)
    return base.isoformat(timespec="seconds")


def campaign_preview(db: Database, campaign_id: str):
    now = utcnow()
    with db.connect() as con:
        camp = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not camp:
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        selected, skipped = _eligible_destinations(con, camp)
        variants = [dict(r) for r in _campaign_content_rows(con, campaign_id)]
        by_account = {"primary_only": 0, "secondary_only": 0, "both": 0}
        by_mode = {"photo": 0, "text": 0}
        for d in selected:
            if d["primary_access"] and d["secondary_access"]: by_account["both"] += 1
            elif d["primary_access"]: by_account["primary_only"] += 1
            elif d["secondary_access"]: by_account["secondary_only"] += 1
            by_mode[d["mode"]] = by_mode.get(d["mode"], 0) + 1
        return {
            "campaign_id": campaign_id,
            "name": camp["name"],
            "enabled": bool(camp["enabled"]),
            "lifecycle_state": camp["lifecycle_state"] if "lifecycle_state" in camp.keys() else ("active" if camp["enabled"] else "draft"),
            "last_preview_at": camp["last_preview_at"] if "last_preview_at" in camp.keys() else None,
            "active": _campaign_active(camp, now)[0],
            "rotation_mode": camp["rotation_mode"],
            "variant_count": len(variants),
            "variants": [r["content_id"] for r in variants],
            "selected": len(selected),
            "accounts": by_account,
            "modes": by_mode,
            "skipped": skipped,
            "include_tags": sorted(_csv_tags(camp["target_tags"])),
            "exclude_tags": sorted(_csv_tags(camp["exclude_tags"])),
            "collections": sorted(_csv_tags(camp["target_collections"])) if "target_collections" in camp.keys() else [],
            "category": camp["category"] if "category" in camp.keys() else "",
            "max_cycles": int(camp["max_cycles"] or 0) if "max_cycles" in camp.keys() else 0,
            "completed_cycles": int(camp["completed_cycles"] or 0) if "completed_cycles" in camp.keys() else 0,
            "allow_protected": bool(camp["allow_protected"]),
            "conflict_gap_seconds": int(camp["conflict_gap_seconds"] or 0),
            "spread_seconds": int(camp["spread_seconds"] or 0) if "spread_seconds" in camp.keys() else 0,
        }


def enqueue_campaign(db: Database, campaign_id: str, dry_run=False, run_key: str | None = None, limits: dict | None = None):
    now = utcnow()
    with db.connect() as con:
        camp = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not camp:
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        if not camp["enabled"]:
            raise RuntimeError(f"Campaign is disabled: {campaign_id}")
        max_cycles = int(camp["max_cycles"] or 0) if "max_cycles" in camp.keys() else 0
        completed_cycles = int(camp["completed_cycles"] or 0) if "completed_cycles" in camp.keys() else 0
        if max_cycles and completed_cycles >= max_cycles:
            raise RuntimeError(f"Campaign cycle limit reached: {completed_cycles}/{max_cycles}")
        active, reason = _campaign_active(camp, now)
        if not active:
            raise RuntimeError(reason)
        variants = _campaign_content_rows(con, campaign_id)
        if not variants:
            raise RuntimeError(f"Campaign has no enabled content: {campaign_id}")
        selected, skipped = _eligible_destinations(con, camp)
        key = run_key or f"manual:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')}"
        preview = campaign_preview(db, campaign_id) if dry_run else None
        if dry_run:
            return {"selected": len(selected), "inserted": 0, "duplicates": 0, "run_key": key, "preview": preview}

        if limits:
            from .operations import enforce_queue_limits
            enforce_queue_limits(
                db, add_count=len(selected), campaign_id=campaign_id, group_ids=[int(d["group_id"]) for d in selected],
                max_queue_size=int(limits.get("max_queue_size", 50000)),
                max_pending_per_campaign=int(limits.get("max_pending_per_campaign", 10000)),
                max_pending_per_destination=int(limits.get("max_pending_per_destination", 100)),
            )

        inserted = dup = 0
        due_values = []
        content_counts: dict[str, int] = {}
        for d in selected:
            content_id = _select_content(con, camp, d["group_id"])
            raw = f"{campaign_id}|{d['group_id']}|{key}"
            job_key = hashlib.sha256(raw.encode()).hexdigest()
            due_at = _next_due(con, d, camp, now, key)
            try:
                con.execute('''INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?)''',
                            (job_key, key, campaign_id, d["group_id"], content_id, due_at, "pending", now, now))
                inserted += 1
                due_values.append(due_at)
                content_counts[content_id] = content_counts.get(content_id, 0) + 1
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    dup += 1
                else:
                    raise
        if inserted > 0:
            con.execute("UPDATE campaigns SET completed_cycles=completed_cycles+1,updated_at=? WHERE campaign_id=?", (utcnow(), campaign_id))
        return {
            "selected": len(selected), "inserted": inserted, "duplicates": dup, "run_key": key,
            "content_distribution": content_counts,
            "first_due_at": min(due_values) if due_values else None,
            "last_due_at": max(due_values) if due_values else None,
            "skipped": skipped,
        }


def record_content_sent(db: Database, campaign_id: str, group_id: int, content_id: str, sent_at: str | None = None):
    sent_at = sent_at or utcnow()
    with db.connect() as con:
        con.execute('''INSERT INTO content_usage(campaign_id,group_id,content_id,last_used_at,use_count)
                       VALUES(?,?,?,?,1) ON CONFLICT(campaign_id,group_id,content_id) DO UPDATE SET
                       last_used_at=excluded.last_used_at,use_count=content_usage.use_count+1''',
                    (campaign_id, group_id, content_id, sent_at))
        con.execute('''INSERT INTO campaign_destination_state(campaign_id,group_id,last_content_id,last_used_at,send_count)
                       VALUES(?,?,?,?,1) ON CONFLICT(campaign_id,group_id) DO UPDATE SET
                       last_content_id=excluded.last_content_id,last_used_at=excluded.last_used_at,
                       send_count=campaign_destination_state.send_count+1''',
                    (campaign_id, group_id, content_id, sent_at))


def refresh_system_tags(db: Database):
    """Rebuild AUTO_* tags from current destination access/type state."""
    changed = 0
    with db.connect() as con:
        rows = con.execute("SELECT * FROM destinations").fetchall()
        for d in rows:
            con.execute("DELETE FROM destination_tags WHERE group_id=? AND tag LIKE 'auto_%'", (d["group_id"],))
            tags = set()
            if d["primary_access"] and d["secondary_access"]: tags.add("auto_both_accounts")
            elif d["primary_access"]: tags.add("auto_primary_only")
            elif d["secondary_access"]: tags.add("auto_secondary_only")
            if d["mode"] == "photo": tags.add("auto_photo")
            if d["mode"] == "text": tags.add("auto_text")
            if d["forum"]: tags.add("auto_forum")
            if d["needs_review"]: tags.add("auto_review")
            if d["protected"]: tags.add("auto_protected")
            if d["never_auto_post"]: tags.add("auto_never_post")
            for tag in tags:
                con.execute("INSERT OR IGNORE INTO destination_tags(group_id,tag) VALUES(?,?)", (d["group_id"], tag))
            changed += len(tags)
    return changed


def repair_routing_preferences(db: Database):
    """Repair stale account preferences after a live access scan."""
    now = utcnow()
    changed_primary = 0
    changed_secondary = 0
    with db.connect() as con:
        cur = con.execute(
            """UPDATE destinations SET preferred_account='primary', updated_at=?
               WHERE preferred_account='secondary' AND secondary_access=0 AND primary_access=1""", (now,))
        changed_primary = cur.rowcount
        cur = con.execute(
            """UPDATE destinations SET preferred_account='secondary', updated_at=?
               WHERE preferred_account='primary' AND primary_access=0 AND secondary_access=1""", (now,))
        changed_secondary = cur.rowcount
    return {"to_primary": changed_primary, "to_secondary": changed_secondary, "total": changed_primary + changed_secondary}


def validate(db: Database):
    problems = []
    with db.connect() as con:
        for c in con.execute("SELECT * FROM content WHERE enabled=1"):
            try:
                media = json.loads(c["media_json"] or "[]")
            except Exception:
                problems.append(f"content {c['content_id']}: media_json is invalid")
                continue
            for p in media:
                if not Path(p).exists():
                    problems.append(f"content {c['content_id']}: missing media {p}")

        for d in con.execute("SELECT * FROM destinations WHERE enabled=1"):
            if d["needs_review"]:
                problems.append(f"destination {d['group_id']} enabled but needs_review=1")
            if d["mode"] not in {"photo", "text"}:
                problems.append(f"destination {d['group_id']} enabled with mode={d['mode']}")
            if not (d["primary_access"] or d["secondary_access"]):
                problems.append(f"destination {d['group_id']} enabled but no account currently has access")
            if d["preferred_account"] not in {"primary", "secondary", "both"}:
                problems.append(f"destination {d['group_id']} invalid preferred_account={d['preferred_account']}")
            if d["preferred_account"] == "primary" and not d["primary_access"] and d["secondary_access"]:
                problems.append(f"destination {d['group_id']} prefers primary but only secondary currently has access; run a live scan")
            if d["preferred_account"] == "secondary" and not d["secondary_access"] and d["primary_access"]:
                problems.append(f"destination {d['group_id']} prefers secondary but only primary currently has access; run a live scan")
            if int(d["min_interval_seconds"] or 0) < 0:
                problems.append(f"destination {d['group_id']} has negative min_interval_seconds")
            if bool(d["quiet_start"]) != bool(d["quiet_end"]):
                problems.append(f"destination {d['group_id']} must set both quiet_start and quiet_end")
            if d["quiet_start"] and d["quiet_end"]:
                try:
                    parse_hhmm(d["quiet_start"]); parse_hhmm(d["quiet_end"])
                    if d["quiet_start"] == d["quiet_end"]:
                        problems.append(f"destination {d['group_id']} quiet_start and quiet_end cannot be equal")
                except ValueError as exc:
                    problems.append(f"destination {d['group_id']}: {exc}")

        # Structural campaign references must be valid even while a campaign is still a draft.
        # Drafts may be incomplete in content/scheduling, but they must not silently retain
        # references to collections that no longer exist or impossible cycle limits.
        for camp in con.execute("SELECT * FROM campaigns"):
            if "max_cycles" in camp.keys() and int(camp["max_cycles"] or 0) < 0:
                problems.append(f"campaign {camp['campaign_id']} max_cycles cannot be negative")
            if "target_collections" in camp.keys():
                for cid in _csv_tags(camp["target_collections"]):
                    if not con.execute("SELECT 1 FROM destination_collections WHERE collection_id=? AND enabled=1", (cid,)).fetchone():
                        problems.append(f"campaign {camp['campaign_id']} references missing/disabled collection {cid}")

        for camp in con.execute("SELECT * FROM campaigns WHERE enabled=1"):
            if camp["rotation_mode"] not in ROTATION_MODES:
                problems.append(f"campaign {camp['campaign_id']} has invalid rotation_mode={camp['rotation_mode']}")
            variants = con.execute('''SELECT COUNT(*) FROM campaign_content cc JOIN content ct ON ct.content_id=cc.content_id
                                      WHERE cc.campaign_id=? AND cc.enabled=1 AND ct.enabled=1''', (camp["campaign_id"],)).fetchone()[0]
            if not variants:
                problems.append(f"campaign {camp['campaign_id']} has no enabled content variants")
            if not (0 <= int(camp["priority"]) <= 100):
                problems.append(f"campaign {camp['campaign_id']} priority outside 0..100")
            if camp["start_at"] and camp["end_at"] and camp["start_at"] >= camp["end_at"]:
                problems.append(f"campaign {camp['campaign_id']} start_at must be before end_at")
            if int(camp["min_content_reuse_seconds"] or 0) < 0 or int(camp["conflict_gap_seconds"] or 0) < 0:
                problems.append(f"campaign {camp['campaign_id']} has negative timing rules")

        for sched in con.execute("SELECT * FROM campaign_schedules WHERE enabled=1"):
            if sched["mode"] == "interval" and int(sched["interval_seconds"] or 0) < 60:
                problems.append(f"schedule {sched['campaign_id']} interval must be >= 60 seconds")
            if sched["mode"] == "daily":
                try:
                    times = json.loads(sched["daily_times_json"] or "[]")
                    if not times:
                        problems.append(f"schedule {sched['campaign_id']} has no daily times")
                    for value in times:
                        parse_hhmm(value)
                except Exception as exc:
                    problems.append(f"schedule {sched['campaign_id']} invalid daily times: {exc}")

        orphan = con.execute("SELECT COUNT(*) FROM queue q LEFT JOIN destinations d ON d.group_id=q.group_id WHERE d.group_id IS NULL").fetchone()[0]
        if orphan:
            problems.append(f"{orphan} orphan queue jobs")
        missing_qcontent = con.execute("SELECT COUNT(*) FROM queue q LEFT JOIN content c ON c.content_id=q.content_id WHERE q.content_id IS NOT NULL AND c.content_id IS NULL").fetchone()[0]
        if missing_qcontent:
            problems.append(f"{missing_qcontent} queue jobs reference missing content")
    return problems
