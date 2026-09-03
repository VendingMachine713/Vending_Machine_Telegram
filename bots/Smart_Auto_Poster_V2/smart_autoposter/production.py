from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .collections import collection_preview, get_collection
from .core import add_campaign_content, campaign_preview, create_campaign, refresh_system_tags, record_content_sent
from .db import Database, utcnow
from .operations import mark_campaign_previewed, set_campaign_state, set_content_tags
from .scheduler import configure_interval, simulate_schedules


@dataclass(frozen=True)
class ProductionBootstrapSpec:
    campaign_id: str = "main_production_01"
    name: str = "Main Production Campaign"
    collection_id: str = "all_approved"
    content_prefix: str = "main_ad_"
    explicit_content_ids: tuple[str, ...] = ()
    exclude_tags: str = "live_test"
    rotation: str = "least_recent"
    interval_minutes: int = 240
    priority: int = 100
    reuse_minutes: int = 1440
    conflict_gap_minutes: int = 60
    spread_minutes: int = 0
    category: str = "production"
    content_tags: tuple[str, ...] = ("production", "main_ads")
    canary_campaign_id: str = "album_canary_01"
    canary_collection_id: str = "live_test"
    configure_canary: bool = True


def _enabled_content(db: Database, spec: ProductionBootstrapSpec) -> list[dict]:
    with db.connect() as con:
        if spec.explicit_content_ids:
            placeholders = ",".join("?" for _ in spec.explicit_content_ids)
            rows = con.execute(
                f"SELECT content_id,caption,media_json,lifecycle_state,enabled FROM content WHERE content_id IN ({placeholders}) ORDER BY content_id",
                list(spec.explicit_content_ids),
            ).fetchall()
            found = {str(r["content_id"]) for r in rows}
            missing = [x for x in spec.explicit_content_ids if x not in found]
            if missing:
                raise RuntimeError("Unknown content: " + ", ".join(missing))
        else:
            rows = con.execute(
                "SELECT content_id,caption,media_json,lifecycle_state,enabled FROM content WHERE enabled=1 AND content_id LIKE ? ORDER BY content_id",
                (f"{spec.content_prefix}%",),
            ).fetchall()
    usable = []
    for row in rows:
        if not bool(row["enabled"]) or str(row["lifecycle_state"] or "") != "ready":
            continue
        try:
            media = json.loads(row["media_json"] or "[]")
        except Exception:
            media = []
        usable.append({
            "content_id": str(row["content_id"]),
            "caption": str(row["caption"] or ""),
            "media": list(media),
        })
    if not usable:
        raise RuntimeError("No enabled READY production content matched the requested selection")
    return usable


def _sync_campaign_variants(db: Database, campaign_id: str, content_ids: list[str]):
    with db.connect() as con:
        if content_ids:
            placeholders = ",".join("?" for _ in content_ids)
            con.execute(
                f"UPDATE campaign_content SET enabled=0 WHERE campaign_id=? AND content_id NOT IN ({placeholders})",
                [campaign_id, *content_ids],
            )
    for pos, cid in enumerate(content_ids):
        add_campaign_content(db, campaign_id, cid, position=pos, weight=1, enabled=True)


def _configure_album_canary(db: Database, spec: ProductionBootstrapSpec, first_content_id: str) -> dict | None:
    if not spec.configure_canary:
        return None
    try:
        canary_collection = get_collection(db, spec.canary_collection_id)
    except RuntimeError:
        return {"configured": False, "reason": f"collection missing: {spec.canary_collection_id}"}
    if not bool(canary_collection.get("enabled")):
        return {"configured": False, "reason": f"collection disabled: {spec.canary_collection_id}"}

    canary_preview = collection_preview(db, spec.canary_collection_id)
    if canary_preview["selected"] != 1:
        return {"configured": False, "reason": f"expected exactly one canary destination, got {canary_preview['selected']}"}

    gid = int(canary_preview["group_ids"][0])
    collection_mode_before = str(canary_collection.get("mode") or "any").lower()
    with db.connect() as con:
        # The permanent canary must be photo-mode so Telegram media-group
        # behaviour can be verified. Earlier V3 setup guides created LIVE_TEST
        # with mode=text; changing only the destination to photo made that
        # collection immediately filter its own canary out. Repair both sides
        # atomically while preserving the collection's tag/access/protection
        # rules.
        con.execute(
            "UPDATE destination_collections SET mode='photo',updated_at=? WHERE collection_id=?",
            (utcnow(), spec.canary_collection_id.strip().lower()),
        )
        con.execute("UPDATE destinations SET mode='photo',updated_at=? WHERE group_id=?", (utcnow(), gid))
        legacy = con.execute("SELECT 1 FROM campaigns WHERE campaign_id='live_test_001'").fetchone()
    refresh_system_tags(db)

    repaired_preview = collection_preview(db, spec.canary_collection_id)
    if repaired_preview["selected"] != 1 or int(repaired_preview["group_ids"][0]) != gid:
        raise RuntimeError(
            f"album canary collection lost its destination after photo-mode repair: "
            f"collection={spec.canary_collection_id} selected={repaired_preview['selected']} expected_group_id={gid}"
        )
    if legacy:
        try:
            set_campaign_state(db, "live_test_001", "paused", actor="production-bootstrap")
        except Exception:
            pass

    create_campaign(
        db,
        spec.canary_campaign_id,
        "Album Canary",
        first_content_id,
        priority=100,
        tags="",
        exclude_tags="",
        rotation_mode="sequential",
        allow_protected=False,
        conflict_gap_seconds=0,
        spread_seconds=0,
        category="canary",
        target_collections=spec.canary_collection_id,
        max_cycles=0,
    )
    _sync_campaign_variants(db, spec.canary_campaign_id, [first_content_id])
    mark_campaign_previewed(db, spec.canary_campaign_id, actor="production-bootstrap")
    set_campaign_state(db, spec.canary_campaign_id, "ready", actor="production-bootstrap")
    preview = campaign_preview(db, spec.canary_campaign_id)
    return {
        "configured": True,
        "campaign_id": spec.canary_campaign_id,
        "destination_id": gid,
        "content_id": first_content_id,
        "collection_mode_before": collection_mode_before,
        "collection_mode_after": "photo",
        "preview": preview,
    }


def bootstrap_production(db: Database, timezone_name: str, spec: ProductionBootstrapSpec) -> dict:
    if spec.interval_minutes < 1:
        raise ValueError("interval_minutes must be >= 1")
    if not (0 <= spec.priority <= 100):
        raise ValueError("priority must be 0-100")

    target = collection_preview(db, spec.collection_id)
    if not target["enabled"]:
        raise RuntimeError(f"Production collection is disabled: {spec.collection_id}")
    if target["selected"] < 1:
        raise RuntimeError(f"Production collection selects no destinations: {spec.collection_id}")

    content = _enabled_content(db, spec)
    content_ids = [x["content_id"] for x in content]
    for item in content:
        if not item["caption"]:
            raise RuntimeError(f"Production content has an empty caption: {item['content_id']}")
        if len(item["media"]) < 1:
            raise RuntimeError(f"Production content has no media: {item['content_id']}")
        if len(item["media"]) > 10:
            raise RuntimeError(f"Production content exceeds the 10-item Telegram album limit: {item['content_id']} ({len(item['media'])})")
        for path in item["media"]:
            if not Path(path).exists():
                raise RuntimeError(f"Production content media is missing: {item['content_id']} -> {path}")
        set_content_tags(db, item["content_id"], add=list(spec.content_tags), actor="production-bootstrap")

    create_campaign(
        db,
        spec.campaign_id,
        spec.name,
        content_ids[0],
        priority=spec.priority,
        tags="",
        exclude_tags=spec.exclude_tags,
        rotation_mode=spec.rotation,
        min_content_reuse_seconds=spec.reuse_minutes * 60,
        allow_protected=False,
        conflict_gap_seconds=spec.conflict_gap_minutes * 60,
        spread_seconds=spec.spread_minutes * 60,
        category=spec.category,
        target_collections=spec.collection_id,
        max_cycles=0,
    )
    _sync_campaign_variants(db, spec.campaign_id, content_ids)

    # The schedule is configured but the campaign stays READY/inactive. The
    # first run is one full interval away, avoiding an accidental immediate send
    # when the campaign is later activated.
    configure_interval(
        db,
        spec.campaign_id,
        spec.interval_minutes * 60,
        timezone_name,
        start_in_seconds=spec.interval_minutes * 60,
    )
    mark_campaign_previewed(db, spec.campaign_id, actor="production-bootstrap")
    set_campaign_state(db, spec.campaign_id, "ready", actor="production-bootstrap")

    preview = campaign_preview(db, spec.campaign_id)
    simulation = simulate_schedules(db, hours=24, include_inactive=True, campaign_id=spec.campaign_id)
    canary = _configure_album_canary(db, spec, content_ids[0])

    with db.connect() as con:
        schedule = con.execute(
            "SELECT mode,interval_seconds,timezone,next_run_at,enabled FROM campaign_schedules WHERE campaign_id=?",
            (spec.campaign_id,),
        ).fetchone()

    return {
        "campaign_id": spec.campaign_id,
        "state": "ready",
        "content_ids": content_ids,
        "content_count": len(content_ids),
        "content_media_counts": {x["content_id"]: len(x["media"]) for x in content},
        "collection": target,
        "preview": preview,
        "schedule": dict(schedule) if schedule else None,
        "simulation_24h": simulation,
        "canary": canary,
        "activation_required": True,
        "send_performed": False,
    }


def production_readiness(db: Database, campaign_id: str, *, expected_collection: str | None = None) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    with db.connect() as con:
        campaign = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not campaign:
            return {"ok": False, "campaign_id": campaign_id, "problems": ["campaign not found"], "warnings": []}
        variants = con.execute(
            """SELECT ct.content_id,ct.caption,ct.media_json,ct.enabled,ct.lifecycle_state
               FROM campaign_content cc JOIN content ct ON ct.content_id=cc.content_id
               WHERE cc.campaign_id=? AND cc.enabled=1 ORDER BY cc.position,ct.content_id""",
            (campaign_id,),
        ).fetchall()
        schedule = con.execute("SELECT * FROM campaign_schedules WHERE campaign_id=?", (campaign_id,)).fetchone()
        active_queue = con.execute(
            "SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN ('pending','retry','processing','sending','deferred')",
            (campaign_id,),
        ).fetchone()[0]

    preview = campaign_preview(db, campaign_id)
    collections = [x.strip().lower() for x in str(campaign["target_collections"] or "").split(",") if x.strip()]
    if expected_collection and expected_collection.lower() not in collections:
        problems.append(f"expected collection missing: {expected_collection}")
    if preview["selected"] < 1:
        problems.append("campaign selects no destinations")
    if "live_test" not in {x.strip().lower() for x in str(campaign["exclude_tags"] or "").split(",") if x.strip()} and campaign_id != "album_canary_01":
        warnings.append("live_test is not explicitly excluded")
    if bool(campaign["allow_protected"]):
        problems.append("protected destinations are allowed")
    if not variants:
        problems.append("no enabled content variants")
    media_counts = {}
    text_compatible_variants = 0
    photo_compatible_variants = 0
    for row in variants:
        try:
            media = json.loads(row["media_json"] or "[]")
        except Exception:
            media = []
        media_counts[str(row["content_id"])] = len(media)
        if not row["caption"]:
            warnings.append(f"content has no text-only payload: {row['content_id']}")
        else:
            text_compatible_variants += 1
        if 1 <= len(media) <= 10:
            photo_compatible_variants += 1
        if not bool(row["enabled"]) or str(row["lifecycle_state"]) != "ready":
            problems.append(f"content not READY: {row['content_id']}")
        if len(media) > 10:
            problems.append(f"album exceeds 10 items: {row['content_id']}")
    if not schedule:
        warnings.append("no schedule configured")
    if int(active_queue or 0):
        warnings.append(f"campaign already has {int(active_queue)} active queue job(s)")

    media_bearing_variants = sum(1 for count in media_counts.values() if int(count or 0) > 0)
    text_destinations = int((preview.get("modes") or {}).get("text") or 0)
    photo_destinations = int((preview.get("modes") or {}).get("photo") or 0)
    media_delivery = {
        "media_bearing_variants": media_bearing_variants,
        "text_compatible_variants": text_compatible_variants,
        "photo_compatible_variants": photo_compatible_variants,
        "photo_destinations": photo_destinations,
        "text_destinations": text_destinations,
        "text_destinations_receive_caption_only": bool(media_bearing_variants and text_destinations),
        "mixed_mode_supported": True,
    }
    if text_destinations and text_compatible_variants < 1:
        problems.append("text-mode destinations selected but no content variant has a non-empty caption")
    if photo_destinations and photo_compatible_variants < 1:
        problems.append("photo-mode destinations selected but no content variant has valid 1..10 media")
    if media_delivery["text_destinations_receive_caption_only"]:
        warnings.append(
            f"mixed delivery active: {text_destinations} text-mode destination(s) receive caption-only posts; "
            f"{photo_destinations} photo-mode destination(s) receive media"
        )

    return {
        "ok": not problems,
        "campaign_id": campaign_id,
        "state": str(campaign["lifecycle_state"]),
        "enabled": bool(campaign["enabled"]),
        "selected": preview["selected"],
        "accounts": preview["accounts"],
        "modes": preview["modes"],
        "collections": preview.get("collections") or [],
        "variants": [str(r["content_id"]) for r in variants],
        "media_counts": media_counts,
        "media_delivery": media_delivery,
        "schedule": dict(schedule) if schedule else None,
        "active_queue_jobs": int(active_queue or 0),
        "problems": problems,
        "warnings": warnings,
    }



def canary_queue_status(db: Database, campaign_id: str = "album_canary_01") -> dict:
    """Return a machine-readable status for the already-approved album canary.

    This never enqueues, activates, or sends anything. It exists so the Windows
    retry orchestrator can resume the *same* queued job after Telegram slow mode
    without creating duplicates.
    """
    with db.connect() as con:
        row = con.execute(
            """SELECT q.id,q.status,q.attempts,q.max_attempts,q.due_at,q.error_kind,
                      q.last_error,q.telegram_message_ids,q.group_id,q.content_id,
                      d.group_name,c.enabled AS campaign_enabled,c.lifecycle_state
               FROM queue q
               JOIN destinations d ON d.group_id=q.group_id
               JOIN campaigns c ON c.campaign_id=q.campaign_id
               WHERE q.campaign_id=? ORDER BY q.id DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
    if not row:
        return {
            "ok": False,
            "campaign_id": campaign_id,
            "job_found": False,
            "status": None,
            "resume_required": False,
            "problem": "no canary queue job exists",
        }
    result = dict(row)
    due_raw = str(result.get("due_at") or "")
    due = None
    seconds_until_due = 0
    if due_raw:
        try:
            due = datetime.fromisoformat(due_raw)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            seconds_until_due = max(0, int((due - datetime.now(timezone.utc)).total_seconds()))
        except ValueError:
            pass
    status = str(result.get("status") or "")
    result.update({
        "ok": status in {"pending", "retry", "deferred", "uncertain", "sent"},
        "campaign_id": campaign_id,
        "job_found": True,
        "due": seconds_until_due == 0,
        "seconds_until_due": seconds_until_due,
        "resume_required": status in {"pending", "retry", "deferred"},
        "visual_reconciliation_available": status in {"retry", "uncertain", "deferred", "pending"},
        "completed": status == "sent",
    })
    return result



def reconcile_visual_canary_sent(
    db: Database,
    *,
    campaign_id: str = "album_canary_01",
    job_id: int,
    confirmation: str,
    actor: str = "visual-canary-reconcile",
) -> dict:
    """Resolve an acknowledgement-ambiguous canary after explicit visual verification.

    This performs NO Telegram send. It is intentionally narrower than generic job
    management: only the latest 10-photo LIVE_TEST canary job can be reconciled, and
    only after an exact explicit confirmation token.
    """
    if confirmation != "ALBUM_VISUALLY_CONFIRMED_SENT":
        raise RuntimeError("Explicit confirmation ALBUM_VISUALLY_CONFIRMED_SENT is required")
    now = utcnow()
    with db.connect() as con:
        latest = con.execute(
            """SELECT q.*,d.group_name,d.mode,c.lifecycle_state,c.enabled AS campaign_enabled,ct.media_json
               FROM queue q
               JOIN destinations d ON d.group_id=q.group_id
               JOIN campaigns c ON c.campaign_id=q.campaign_id
               JOIN content ct ON ct.content_id=q.content_id
               WHERE q.campaign_id=? ORDER BY q.id DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
        if not latest:
            raise RuntimeError("No album canary queue job exists")
        row = dict(latest)
        if int(row["id"]) != int(job_id):
            raise RuntimeError(f"Canary reconciliation is bound to latest job #{row['id']}, not #{job_id}")
        if str(row.get("status")) == "sent":
            return {"ok": True, "already_sent": True, "job_id": int(row["id"]), "status": "sent"}
        if str(row.get("status")) not in {"retry", "uncertain", "deferred", "pending"}:
            raise RuntimeError(f"Canary job status {row.get('status')} is not eligible for visual reconciliation")
        if str(row.get("mode")) != "photo":
            raise RuntimeError("Canary destination is not photo-mode")
        try:
            media = json.loads(row.get("media_json") or "[]")
        except Exception:
            media = []
        if len(media) != 10:
            raise RuntimeError(f"Expected exactly 10 media files for album canary; got {len(media)}")
        tagged = con.execute(
            "SELECT 1 FROM destination_tags WHERE group_id=? AND lower(tag)='live_test'",
            (int(row["group_id"]),),
        ).fetchone()
        if not tagged:
            raise RuntimeError("Canary destination is not tagged live_test")
        con.execute(
            """UPDATE queue SET status='sent',error_kind='visual_reconciled_sent',
                       last_error='Telegram acknowledgement was ambiguous; visually confirmed delivered album',
                       resolved_at=?,phase='sent',phase_percent=100,
                       phase_detail='visual confirmation verified Telegram delivery',phase_updated_at=?,updated_at=? WHERE id=?""",
            (now, now, now, int(row["id"])),
        )
        con.execute(
            "UPDATE campaigns SET lifecycle_state='paused',enabled=0,updated_at=? WHERE campaign_id=?",
            (now, campaign_id),
        )
        con.execute(
            "UPDATE destinations SET last_post_at=?,updated_at=? WHERE group_id=?",
            (now, now, int(row["group_id"])),
        )
    record_content_sent(db, campaign_id, int(row["group_id"]), str(row["content_id"]), now)
    db.audit(
        actor,
        "canary_visual_reconciled_sent",
        target_type="queue_job",
        target_id=str(row["id"]),
        details=json.dumps({
            "campaign_id": campaign_id,
            "group_id": int(row["group_id"]),
            "content_id": str(row["content_id"]),
            "previous_status": str(row.get("status")),
            "confirmation": confirmation,
        }, ensure_ascii=False),
    )
    db.event(
        "WARNING",
        "canary_visual_reconciled_sent",
        "Canary marked sent from explicit visual verification after ambiguous Telegram acknowledgement; no resend performed",
        group_id=int(row["group_id"]),
        campaign_id=campaign_id,
    )
    return {
        "ok": True,
        "already_sent": False,
        "job_id": int(row["id"]),
        "status": "sent",
        "previous_status": str(row.get("status")),
        "group_id": int(row["group_id"]),
        "group_name": row.get("group_name"),
        "content_id": str(row["content_id"]),
        "media_count": 10,
        "telegram_send_performed": False,
        "reconciliation": "visual_confirmation",
    }

def album_delivery_plan(db: Database, campaign_id: str = "main_production_01") -> dict:
    """Describe how an album-bearing campaign will be delivered without changing state."""
    ready = production_readiness(db, campaign_id)
    preview = campaign_preview(db, campaign_id)
    group_ids = [int(x) for x in preview.get("group_ids") or []]
    rows: list[dict] = []
    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        with db.connect() as con:
            db_rows = con.execute(
                f"""SELECT group_id,group_name,mode,primary_access,secondary_access,preferred_account,
                           protected,never_auto_post,needs_review,enabled
                    FROM destinations WHERE group_id IN ({placeholders}) ORDER BY lower(group_name),group_id""",
                group_ids,
            ).fetchall()
        rows = [dict(r) for r in db_rows]
    photo = [r for r in rows if str(r.get("mode")) == "photo"]
    text = [r for r in rows if str(r.get("mode")) == "text"]
    return {
        "ok": bool(ready.get("ok")),
        "campaign_id": campaign_id,
        "campaign_state": ready.get("state"),
        "campaign_enabled": bool(ready.get("enabled")),
        "selected": len(rows),
        "photo_destinations": len(photo),
        "text_destinations": len(text),
        "caption_only_if_unchanged": len(text),
        "album_if_unchanged": len(photo),
        "requires_mode_migration_for_all_album": bool(text),
        "mixed_mode_delivery_supported": True,
        "mode_migration_required_for_normal_v4_delivery": False,
        "text_destination_rows": text,
        "photo_destination_rows": photo,
        "problems": list(ready.get("problems") or []),
        "warnings": list(ready.get("warnings") or []),
        "changes_performed": False,
    }


def apply_album_delivery_modes(
    db: Database,
    campaign_id: str = "main_production_01",
    *,
    confirmation: str = "",
) -> dict:
    """Convert currently selected text-mode production destinations to photo mode.

    This is deliberately gated and never activates/enqueues/sends. It only changes
    destination delivery mode after an explicit local confirmation string.
    """
    if confirmation != "APPLY_PHOTO_MODE":
        raise RuntimeError("Explicit confirmation APPLY_PHOTO_MODE is required")
    plan = album_delivery_plan(db, campaign_id)
    if not plan["ok"]:
        raise RuntimeError("Production readiness failed; mode migration blocked")
    if plan["campaign_enabled"] or str(plan["campaign_state"]) == "active":
        raise RuntimeError("Campaign must remain inactive while delivery modes are changed")
    with db.connect() as con:
        active_queue = int(con.execute(
            "SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN ('pending','retry','deferred','processing','sending')",
            (campaign_id,),
        ).fetchone()[0])
    if active_queue:
        raise RuntimeError(f"Campaign has {active_queue} active queue job(s); mode migration blocked")

    ids = [int(r["group_id"]) for r in plan["text_destination_rows"]]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        now = utcnow()
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                f"UPDATE destinations SET mode='photo',updated_at=? WHERE group_id IN ({placeholders}) AND mode='text'",
                [now, *ids],
            )
        refresh_system_tags(db)
        for gid in ids:
            db.event(
                "INFO",
                "production_delivery_mode_changed",
                "Explicit all-album preparation changed destination mode text -> photo",
                group_id=gid,
                campaign_id=campaign_id,
            )

    after = album_delivery_plan(db, campaign_id)
    after.update({
        "changes_performed": bool(ids),
        "changed_group_ids": ids,
        "changed_count": len(ids),
    })
    if after["text_destinations"] != 0:
        raise RuntimeError(
            f"All-album invariant failed: {after['text_destinations']} text-mode destination(s) remain"
        )
    return after
