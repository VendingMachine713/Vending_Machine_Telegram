from __future__ import annotations

from .core import refresh_system_tags, repair_routing_preferences
from .db import Database, utcnow
from .topic_routing import sync_forum_topics


async def sync_destinations(db: Database, pool, auth: dict, *, fail_closed: bool = True) -> dict:
    """Synchronize live Telegram dialogs into the destination registry.

    New destinations stay REVIEW + disabled. Lost access fails closed when both user
    accounts are successfully authorized. Renames/forum/access changes are tracked so
    the admin surface can report meaningful changes without treating them as new groups.
    """
    counts = {}
    newly_added = 0
    updated = 0
    renamed = 0
    forum_changed = 0
    access_changed = 0
    now = utcnow()
    with db.connect() as con:
        previous = {
            int(r["group_id"]): dict(r)
            for r in con.execute("SELECT group_id,group_name,forum,primary_access,secondary_access FROM destinations").fetchall()
        }
        seen_by = {"primary": set(), "secondary": set()}
        for key in ("primary", "secondary"):
            if not auth.get(key, {}).get("authorized"):
                counts[key] = None
                continue
            con.execute(f"UPDATE destinations SET {key}_access=0,updated_at=?", (now,))
            dialogs = await pool.dialogs(key)
            counts[key] = len(dialogs)
            for x in dialogs:
                gid = int(x["group_id"])
                seen_by[key].add(gid)
                old = previous.get(gid)
                existing = con.execute("SELECT group_id FROM destinations WHERE group_id=?", (gid,)).fetchone()
                if existing:
                    if old and old.get("group_name") != x["group_name"]:
                        renamed += 1
                    if old and int(old.get("forum") or 0) != int(bool(x["forum"])):
                        forum_changed += 1
                    con.execute(f'''UPDATE destinations SET group_name=?,chat_type=?,username=?,forum=?,{key}_access=1,last_seen_at=?,updated_at=?
                                    WHERE group_id=?''',
                                (x["group_name"], x["chat_type"], x["username"], int(x["forum"]), now, now, gid))
                    updated += 1
                else:
                    con.execute(f'''INSERT INTO destinations(group_id,group_name,chat_type,username,forum,{key}_access,
                                    preferred_account,mode,enabled,needs_review,last_seen_at,updated_at)
                                    VALUES(?,?,?,?,?,1,?,'review',0,1,?,?)''',
                                (gid, x["group_name"], x["chat_type"], x["username"], int(x["forum"]), key, now, now))
                    newly_added += 1

        # Compare access after all authorized account scans have been applied.
        for gid, old in previous.items():
            cur = con.execute("SELECT primary_access,secondary_access FROM destinations WHERE group_id=?", (gid,)).fetchone()
            if not cur:
                continue
            if counts.get("primary") is not None and int(old.get("primary_access") or 0) != int(cur["primary_access"] or 0):
                access_changed += 1
            if counts.get("secondary") is not None and int(old.get("secondary_access") or 0) != int(cur["secondary_access"] or 0):
                access_changed += 1

        lost = 0
        if fail_closed and all(auth.get(k, {}).get("authorized") for k in ("primary", "secondary")):
            cur = con.execute('''UPDATE destinations SET enabled=0,needs_review=1,
                                 notes=TRIM(COALESCE(notes,'') || ' access lost on scan'),updated_at=?
                                 WHERE primary_access=0 AND secondary_access=0 AND enabled=1''', (now,))
            lost = cur.rowcount

    topic_result = await sync_forum_topics(db, pool, auth)
    repaired = repair_routing_preferences(db)
    system_tags = refresh_system_tags(db)
    result = {
        "counts": counts,
        "new": newly_added,
        "updated": updated,
        "renamed": renamed,
        "forum_changed": forum_changed,
        "access_changed": access_changed,
        "lost_disabled": lost,
        "routing_repaired": repaired,
        "system_tags_written": system_tags,
        "topic_routing": topic_result,
    }
    db.event("INFO", "destination_sync", "Telegram destination synchronization complete", details=str(result))
    return result
