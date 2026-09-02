from __future__ import annotations


ACTIVE_QUEUE_STATUSES_SQL = "('pending','retry','sending','deferred')"


def enforce_queue_limits_on_connection(
    con,
    *,
    add_count: int,
    campaign_id: str,
    group_ids: list[int],
    max_queue_size: int,
    max_pending_per_campaign: int,
    max_pending_per_destination: int,
) -> None:
    """Validate queue capacity using the caller's existing write transaction.

    The caller must hold the transaction that will also insert the queue batch. This
    prevents a check-then-insert race where two schedulers both observe spare capacity
    before either batch becomes visible.
    """
    add_count = max(0, int(add_count))
    max_queue_size = int(max_queue_size)
    max_pending_per_campaign = int(max_pending_per_campaign)
    max_pending_per_destination = int(max_pending_per_destination)

    if max_queue_size < 1 or max_pending_per_campaign < 1 or max_pending_per_destination < 1:
        raise ValueError("Queue capacity limits must all be >= 1")

    total = int(
        con.execute(
            f"SELECT COUNT(*) FROM queue WHERE status IN {ACTIVE_QUEUE_STATUSES_SQL}"
        ).fetchone()[0]
    )
    campaign_total = int(
        con.execute(
            f"SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN {ACTIVE_QUEUE_STATUSES_SQL}",
            (campaign_id,),
        ).fetchone()[0]
    )

    if total + add_count > max_queue_size:
        raise RuntimeError(
            f"Queue capacity protection: {total}+{add_count} would exceed MAX_QUEUE_SIZE={max_queue_size}"
        )
    if campaign_total + add_count > max_pending_per_campaign:
        raise RuntimeError(
            f"Campaign queue protection: {campaign_total}+{add_count} would exceed "
            f"MAX_PENDING_PER_CAMPAIGN={max_pending_per_campaign}"
        )

    if not group_ids:
        return

    unique_group_ids = sorted({int(gid) for gid in group_ids})
    placeholders = ",".join("?" for _ in unique_group_ids)
    rows = con.execute(
        f"""SELECT group_id,COUNT(*) AS n
            FROM queue
            WHERE group_id IN ({placeholders})
              AND status IN {ACTIVE_QUEUE_STATUSES_SQL}
            GROUP BY group_id""",
        unique_group_ids,
    ).fetchall()
    counts = {int(r["group_id"]): int(r["n"]) for r in rows}
    additions = {gid: group_ids.count(gid) for gid in unique_group_ids}
    bad = [
        gid
        for gid in unique_group_ids
        if counts.get(gid, 0) + additions[gid] > max_pending_per_destination
    ]
    if bad:
        raise RuntimeError(
            f"Destination queue protection: {len(bad)} destination(s) exceed "
            f"MAX_PENDING_PER_DESTINATION={max_pending_per_destination}"
        )
