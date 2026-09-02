from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from shared.vm_core.progress import GroupProgress, clamp_percent, plain_status, render_bar
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[3]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shared.vm_core.progress import GroupProgress, clamp_percent, plain_status, render_bar

from .db import Database, utcnow


_PROGRESS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS live_progress (
    job_id INTEGER PRIMARY KEY,
    run_key TEXT,
    campaign_id TEXT NOT NULL,
    group_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    stage TEXT NOT NULL,
    percent REAL NOT NULL DEFAULT 0,
    status_text TEXT NOT NULL,
    error_text TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_progress_run_updated ON live_progress(run_key, updated_at);
CREATE INDEX IF NOT EXISTS idx_live_progress_campaign_updated ON live_progress(campaign_id, updated_at);
'''
_SCHEMA_READY: set[str] = set()


def ensure_progress_schema(db: Database) -> None:
    key = str(db.path.resolve())
    if key in _SCHEMA_READY:
        return
    with db.connect() as con:
        con.executescript(_PROGRESS_SCHEMA)
    _SCHEMA_READY.add(key)


def set_group_progress(
    db: Database,
    job: dict,
    stage: str,
    percent: float | int,
    *,
    error: str | None = None,
) -> GroupProgress:
    """Persist the latest progress for one queue job.

    This table is intentionally a latest-state projection, not an event log. The
    existing events and delivery ledger remain the audit trail/source of truth.
    """
    ensure_progress_schema(db)
    progress = GroupProgress.build(
        job_id=int(job["id"]),
        campaign_id=str(job["campaign_id"]),
        group_id=int(job["group_id"]),
        group_name=str(job.get("group_name") or job["group_id"]),
        stage=stage,
        percent=percent,
        error=error,
    )
    with db.connect() as con:
        con.execute(
            '''INSERT INTO live_progress(job_id,run_key,campaign_id,group_id,group_name,stage,percent,status_text,error_text,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 run_key=excluded.run_key,
                 campaign_id=excluded.campaign_id,
                 group_id=excluded.group_id,
                 group_name=excluded.group_name,
                 stage=excluded.stage,
                 percent=excluded.percent,
                 status_text=excluded.status_text,
                 error_text=excluded.error_text,
                 updated_at=excluded.updated_at''',
            (
                progress.job_id,
                job.get("run_key"),
                progress.campaign_id,
                progress.group_id,
                progress.group_name,
                progress.stage,
                progress.percent,
                progress.status,
                progress.error,
                utcnow(),
            ),
        )
    return progress


@dataclass(frozen=True)
class RunProgress:
    run_key: str | None
    campaign_id: str
    total: int
    sent: int
    processed: int
    remaining: int
    failed: int
    uncertain: int
    deferred: int
    retrying: int
    active: int

    @property
    def posted_percent(self) -> float:
        return clamp_percent((self.sent / self.total) * 100.0) if self.total else 0.0

    @property
    def processed_percent(self) -> float:
        return clamp_percent((self.processed / self.total) * 100.0) if self.total else 0.0


def _latest_run(db: Database, campaign_id: str | None = None) -> tuple[str | None, str] | None:
    where = "WHERE run_key IS NOT NULL"
    args: list[object] = []
    if campaign_id:
        where += " AND campaign_id=?"
        args.append(campaign_id)
    with db.connect() as con:
        row = con.execute(
            f'''SELECT run_key,campaign_id,MAX(created_at) latest
                FROM queue {where}
                GROUP BY run_key,campaign_id
                ORDER BY latest DESC LIMIT 1''',
            args,
        ).fetchone()
        if row:
            return row["run_key"], row["campaign_id"]

        fallback_where = ""
        fallback_args: list[object] = []
        if campaign_id:
            fallback_where = "WHERE campaign_id=?"
            fallback_args.append(campaign_id)
        row = con.execute(
            f'''SELECT NULL run_key,campaign_id,MAX(created_at) latest
                FROM queue {fallback_where}
                GROUP BY campaign_id ORDER BY latest DESC LIMIT 1''',
            fallback_args,
        ).fetchone()
    return (None, row["campaign_id"]) if row else None


def run_progress(db: Database, *, run_key: str | None = None, campaign_id: str | None = None) -> RunProgress | None:
    selected_campaign = campaign_id
    if run_key is None:
        selected = _latest_run(db, campaign_id)
        if not selected:
            return None
        run_key, selected_campaign = selected

    if selected_campaign is None:
        with db.connect() as con:
            row = con.execute(
                "SELECT campaign_id FROM queue WHERE run_key=? ORDER BY created_at DESC LIMIT 1",
                (run_key,),
            ).fetchone()
        if not row:
            return None
        selected_campaign = row["campaign_id"]

    if run_key is None:
        where = "campaign_id=? AND run_key IS NULL"
        args = (selected_campaign,)
    else:
        where = "run_key=? AND campaign_id=?"
        args = (run_key, selected_campaign)

    with db.connect() as con:
        rows = con.execute(
            f"SELECT status,COUNT(*) n FROM queue WHERE {where} GROUP BY status",
            args,
        ).fetchall()
    counts = {r["status"]: int(r["n"]) for r in rows}
    total = sum(counts.values())
    sent = counts.get("sent", 0)
    failed = counts.get("failed", 0) + counts.get("quarantined", 0) + counts.get("cancelled", 0) + counts.get("expired", 0)
    uncertain = counts.get("uncertain", 0)
    processed = sent + failed + uncertain
    remaining = max(0, total - sent)
    return RunProgress(
        run_key=run_key,
        campaign_id=str(selected_campaign),
        total=total,
        sent=sent,
        processed=processed,
        remaining=remaining,
        failed=failed,
        uncertain=uncertain,
        deferred=counts.get("deferred", 0),
        retrying=counts.get("retry", 0),
        active=counts.get("sending", 0),
    )


def current_group_progress(db: Database, *, run_key: str | None = None, campaign_id: str | None = None):
    ensure_progress_schema(db)
    clauses: list[str] = []
    args: list[object] = []
    if run_key is not None:
        clauses.append("run_key=?")
        args.append(run_key)
    if campaign_id is not None:
        clauses.append("campaign_id=?")
        args.append(campaign_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with db.connect() as con:
        row = con.execute(
            f'''SELECT * FROM live_progress {where}
                ORDER BY CASE WHEN stage IN ('sent','failed','uncertain','quarantined','cancelled','expired') THEN 1 ELSE 0 END,
                         updated_at DESC LIMIT 1''',
            args,
        ).fetchone()
    return dict(row) if row else None


def progress_text(db: Database, *, campaign_id: str | None = None, bar_width: int = 20) -> str:
    summary = run_progress(db, campaign_id=campaign_id)
    if not summary:
        return "📊 LIVE POSTING PROGRESS\n\nNo queued posting run found."
    current = current_group_progress(db, run_key=summary.run_key, campaign_id=summary.campaign_id)
    lines = [
        "📊 LIVE POSTING PROGRESS",
        "",
        f"Campaign: {summary.campaign_id}",
        f"Overall posted: {render_bar(summary.posted_percent, bar_width)}",
        f"Posted {summary.sent}/{summary.total} | Left to post {summary.remaining} | Problems {summary.failed + summary.uncertain}",
    ]
    if summary.processed != summary.sent:
        lines.append(f"Processed: {render_bar(summary.processed_percent, bar_width)}")
    if current:
        lines.extend(
            [
                "",
                f"Current group: {current['group_name']}",
                render_bar(current["percent"], bar_width),
                f"Now: {current['status_text']}",
            ]
        )
        if current.get("error_text"):
            lines.append(f"Problem: {current['error_text']}")
    if summary.retrying or summary.deferred:
        lines.append(f"Waiting/retrying: {summary.deferred + summary.retrying}")
    if summary.uncertain:
        lines.append(f"Needs verification: {summary.uncertain}")
    return "\n".join(lines)


class TerminalProgressReporter:
    """Low-noise terminal reporter for the same progress state used by Telegram admin.

    Progress is observability, not delivery control. Persistence or display failures
    therefore fail open and must never prevent a Telegram post from being attempted.
    """

    _OVERALL_STAGES = {"claimed", "sent", "failed", "uncertain", "quarantined", "cancelled", "expired"}

    def __init__(self, db: Database, *, stream=None, min_percent_step: int = 5):
        self.db = db
        self.stream = stream or sys.stdout
        self.min_percent_step = max(1, int(min_percent_step))
        self._last_job_id: int | None = None
        self._last_bucket: int | None = None
        self._last_stage: str | None = None

    @staticmethod
    def _fallback_progress(job: dict, stage: str, percent: float | int, error: str | None = None) -> GroupProgress:
        return GroupProgress.build(
            job_id=int(job["id"]),
            campaign_id=str(job["campaign_id"]),
            group_id=int(job["group_id"]),
            group_name=str(job.get("group_name") or job["group_id"]),
            stage=stage,
            percent=percent,
            error=error,
        )

    def _print_overall(self, job: dict) -> None:
        try:
            summary = run_progress(self.db, run_key=job.get("run_key"), campaign_id=job.get("campaign_id"))
            if not summary:
                return
            problems = summary.failed + summary.uncertain
            line = (
                f"[RUN] {render_bar(summary.posted_percent)} | "
                f"posted {summary.sent}/{summary.total} | left {summary.remaining} | problems {problems}"
            )
            print(line, file=self.stream, flush=True)
        except Exception:
            return

    def update(self, job: dict, stage: str, percent: float | int, *, error: str | None = None) -> GroupProgress:
        try:
            progress = set_group_progress(self.db, job, stage, percent, error=error)
        except Exception:
            progress = self._fallback_progress(job, stage, percent, error)
        bucket = int(progress.percent // self.min_percent_step)
        changed = progress.job_id != self._last_job_id or stage != self._last_stage or bucket != self._last_bucket
        if changed:
            try:
                line = f"[POST] {progress.group_name} | {render_bar(progress.percent)} | {plain_status(stage, error=error)}"
                print(line, file=self.stream, flush=True)
            except Exception:
                pass
            if stage in self._OVERALL_STAGES:
                self._print_overall(job)
            self._last_job_id = progress.job_id
            self._last_bucket = bucket
            self._last_stage = stage
        return progress

    def callback(self, job: dict, stage: str = "uploading") -> Callable[[float, float], None]:
        last_bucket: int | None = None

        def _progress(current: float, total: float) -> None:
            nonlocal last_bucket
            try:
                total_value = float(total or 0)
                percent = (float(current) / total_value * 100.0) if total_value > 0 else 0.0
                percent = clamp_percent(percent)
                bucket = int(percent // self.min_percent_step)
                if last_bucket is None or bucket != last_bucket or percent >= 100:
                    last_bucket = bucket
                    self.update(job, stage, percent)
            except Exception:
                return

        return _progress
