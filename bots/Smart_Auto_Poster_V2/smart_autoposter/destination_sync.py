from __future__ import annotations

from .core import refresh_system_tags, repair_routing_preferences
from .db import Database, utcnow


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
    capability_changed = 0
    mode_changed = 0
    capability_disabled = 0
    now = utcnow()
    with db.connect() as con:
        previous = {
            int(r["group_id"]): dict(r)
            for r in con.execute("SELECT group_id,group_name,forum,primary_access,secondary_access,mode,text_allowed,photo_allowed FROM destinations").fetchall()
        }
        seen_by = {"primary": set(), "secondary": set()}
        capability_seen: dict[int, dict[str, list]] = {}
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
                caps = capability_seen.setdefault(gid, {"text": [], "photo": [], "sources": []})
                if x.get("text_allowed") is not None:
                    caps["text"].append(bool(x.get("text_allowed")))
                if x.get("photo_allowed") is not None:
                    caps["photo"].append(bool(x.get("photo_allowed")))
                if x.get("capability_source"):
                    caps["sources"].append(str(x.get("capability_source")))
                existing = con.execute("SELECT group_id FROM destinations WHERE group_id=?", (gid,)).fetchone()
                if existing:
                    if old and old.get("group_name") != x["group_name"]:
                        renamed += 1
                    if old and int(old.get("forum") or 0) != int(bool(x["forum"])):
                        forum_changed += 1
                    text_allowed = x.get("text_allowed")
                    photo_allowed = x.get("photo_allowed")
                    source = x.get("capability_source")
                    capability_sql = ""
                    capability_params = []
                    if text_allowed is not None:
                        capability_sql += ",text_allowed=?"
                        capability_params.append(int(bool(text_allowed)))
                    if photo_allowed is not None:
                        capability_sql += ",photo_allowed=?"
                        capability_params.append(int(bool(photo_allowed)))
                    if source and (text_allowed is not None or photo_allowed is not None):
                        capability_sql += ",capability_source=?,capability_updated_at=?"
                        capability_params.extend([source, now])
                    con.execute(
                        f"UPDATE destinations SET group_name=?,chat_type=?,username=?,forum=?,{key}_access=1,last_seen_at=?,updated_at=?{capability_sql} WHERE group_id=?",
                        (x["group_name"], x["chat_type"], x["username"], int(x["forum"]), now, now, *capability_params, gid),
                    )
                    updated += 1
                else:
                    text_allowed = x.get("text_allowed")
                    photo_allowed = x.get("photo_allowed")
                    source = x.get("capability_source")
                    con.execute(
                        f"INSERT INTO destinations(group_id,group_name,chat_type,username,forum,{key}_access,preferred_account,mode,enabled,needs_review,last_seen_at,text_allowed,photo_allowed,capability_source,capability_updated_at,updated_at) VALUES(?,?,?,?,?,1,?,'review',0,1,?,?,?,?,?,?)",
                        (gid, x["group_name"], x["chat_type"], x["username"], int(x["forum"]), key, now,
                         None if text_allowed is None else int(bool(text_allowed)),
                         None if photo_allowed is None else int(bool(photo_allowed)), source, now if source else None, now),
                    )
                    newly_added += 1
                # Destination row now exists, so the per-account capability FK is safe.
                con.execute("""INSERT INTO destination_account_capabilities
                    (group_id,account_key,text_allowed,photo_allowed,source,observed_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(group_id,account_key) DO UPDATE SET
                    text_allowed=excluded.text_allowed,photo_allowed=excluded.photo_allowed,
                    source=excluded.source,observed_at=excluded.observed_at""",
                    (gid, key,
                     None if x.get("text_allowed") is None else int(bool(x.get("text_allowed"))),
                     None if x.get("photo_allowed") is None else int(bool(x.get("photo_allowed"))),
                     x.get("capability_source"), now))

        # Merge per-account capability observations. One account being allowed is
        # sufficient because account routing can choose it; only mark a capability
        # forbidden when every observed account is forbidden.
        for gid, caps in capability_seen.items():
            text_values = caps["text"]
            photo_values = caps["photo"]
            text_allowed = 1 if any(text_values) else (0 if text_values and all(v is False for v in text_values) else None)
            photo_allowed = 1 if any(photo_values) else (0 if photo_values and all(v is False for v in photo_values) else None)
            old = previous.get(gid)
            if old and ((text_allowed is not None and old.get("text_allowed") != text_allowed) or
                        (photo_allowed is not None and old.get("photo_allowed") != photo_allowed)):
                capability_changed += 1
            sets=[]; params=[]
            if text_allowed is not None:
                sets.append("text_allowed=?"); params.append(text_allowed)
            if photo_allowed is not None:
                sets.append("photo_allowed=?"); params.append(photo_allowed)
            if sets:
                sets.extend(["capability_source=?","capability_updated_at=?","updated_at=?"]); params.extend(["telegram_scan_union", now, now, gid])
                con.execute(f"UPDATE destinations SET {','.join(sets)} WHERE group_id=?", params)

        # Compare access after all authorized account scans have been applied.
        for gid, old in previous.items():
            cur = con.execute("SELECT primary_access,secondary_access FROM destinations WHERE group_id=?", (gid,)).fetchone()
            if not cur:
                continue
            if counts.get("primary") is not None and int(old.get("primary_access") or 0) != int(cur["primary_access"] or 0):
                access_changed += 1
            if counts.get("secondary") is not None and int(old.get("secondary_access") or 0) != int(cur["secondary_access"] or 0):
                access_changed += 1

        # V4 capability routing: align only when Telegram reports a definitive
        # single-format restriction. If neither format is available, fail closed.
        cap_rows = con.execute("SELECT group_id,mode,enabled,text_allowed,photo_allowed FROM destinations").fetchall()
        for row in cap_rows:
            text_ok, photo_ok = row["text_allowed"], row["photo_allowed"]
            target_mode = None
            if text_ok == 1 and photo_ok == 0:
                target_mode = "text"
            elif text_ok == 0 and photo_ok == 1:
                target_mode = "photo"
            if target_mode and row["mode"] != target_mode:
                con.execute("UPDATE destinations SET mode=?,updated_at=? WHERE group_id=?", (target_mode, now, row["group_id"]))
                mode_changed += 1
            if text_ok == 0 and photo_ok == 0 and bool(row["enabled"]):
                con.execute("UPDATE destinations SET enabled=0,needs_review=1,notes=TRIM(COALESCE(notes,'') || ' Telegram reports no supported posting format'),updated_at=? WHERE group_id=?", (now, row["group_id"]))
                capability_disabled += 1

        lost = 0
        if fail_closed and all(auth.get(k, {}).get("authorized") for k in ("primary", "secondary")):
            cur = con.execute('''UPDATE destinations SET enabled=0,needs_review=1,
                                 notes=TRIM(COALESCE(notes,'') || ' access lost on scan'),updated_at=?
                                 WHERE primary_access=0 AND secondary_access=0 AND enabled=1''', (now,))
            lost = cur.rowcount

    repaired = repair_routing_preferences(db)
    system_tags = refresh_system_tags(db)
    result = {
        "counts": counts,
        "new": newly_added,
        "updated": updated,
        "renamed": renamed,
        "forum_changed": forum_changed,
        "access_changed": access_changed,
        "capability_changed": capability_changed,
        "mode_changed": mode_changed,
        "capability_disabled": capability_disabled,
        "lost_disabled": lost,
        "routing_repaired": repaired,
        "system_tags_written": system_tags,
    }
    db.event("INFO", "destination_sync", "Telegram destination synchronization complete", details=str(result))
    return result
