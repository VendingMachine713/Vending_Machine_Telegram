from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from .db import PlatformDB
from .intelligence_audit import AuditQuery, query_intelligence_events
from .intelligence_trust import canonical_entity_id
from .paths import project_root


@dataclass(frozen=True, slots=True)
class ParityPolicy:
    max_missing_subjects: int = 0
    max_extra_subjects: int = 0
    max_score_delta: float = 5.0
    require_legacy_baseline: bool = True


@dataclass(frozen=True, slots=True)
class ParityEvaluation:
    passed: bool
    status: str
    legacy_count: int
    canonical_count: int
    missing_subjects: tuple[str, ...]
    extra_subjects: tuple[str, ...]
    suppression_mismatches: tuple[str, ...]
    score_mismatches: tuple[str, ...]
    automatic_execution: bool = False


def _readonly_legacy_signals(root: Path) -> list[dict[str, Any]]:
    path = PlatformDB(root=root).path
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='intelligence_signals'"
        ).fetchone()
        if exists is None:
            return []
        rows = con.execute(
            "SELECT * FROM intelligence_signals "
            "WHERE status='ACTIVE' AND signal_type='relationship_activity_opportunity'"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _legacy_projection(root: Path) -> dict[str, dict[str, Any]]:
    projected: dict[str, dict[str, Any]] = {}
    for row in _readonly_legacy_signals(root):
        raw_subject = str(row.get("subject_id") or "").strip()
        if not raw_subject:
            continue
        canonical_subject = canonical_entity_id("chat", raw_subject)
        try:
            evidence = json.loads(row.get("evidence_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        if not isinstance(evidence, dict):
            evidence = {}
        projected[canonical_subject] = {
            "score": float(row.get("score") or 0.0),
            "suppressed": bool(evidence.get("suppressed")),
        }
    return projected


def _canonical_projection(root: Path) -> dict[str, dict[str, Any]]:
    rows = query_intelligence_events(
        AuditQuery(
            event_type_prefix="intelligence.inference.relationship_reengagement_opportunity",
            source="vm_core",
            subject_type="chat",
            limit=5000,
        ),
        root=root,
    )
    projected: dict[str, dict[str, Any]] = {}
    for row in rows:
        subject = str(row.get("subject_id") or "").strip()
        if not subject or subject in projected:
            continue
        attributes = _payload(row).get("attributes")
        if not isinstance(attributes, dict):
            continue
        try:
            score = float(attributes.get("opportunity_score") or 0.0)
        except (TypeError, ValueError):
            continue
        projected[subject] = {
            "score": score,
            "suppressed": bool(attributes.get("suppressed")),
        }
    return projected


def evaluate_legacy_canonical_parity(
    *,
    root: Path | None = None,
    policy: ParityPolicy | None = None,
) -> ParityEvaluation:
    """Compare established legacy opportunity state with canonical inference output.

    This is a passive migration quality gate. It creates no state and grants no
    recommendation or execution authority.
    """
    root = root or project_root()
    policy = policy or ParityPolicy()
    legacy = _legacy_projection(root)
    canonical = _canonical_projection(root)

    legacy_subjects = set(legacy)
    canonical_subjects = set(canonical)
    missing = tuple(sorted(legacy_subjects - canonical_subjects))
    extra = tuple(sorted(canonical_subjects - legacy_subjects))
    suppression_mismatches: list[str] = []
    score_mismatches: list[str] = []

    for subject in sorted(legacy_subjects & canonical_subjects):
        if legacy[subject]["suppressed"] != canonical[subject]["suppressed"]:
            suppression_mismatches.append(subject)
        if abs(legacy[subject]["score"] - canonical[subject]["score"]) > max(
            0.0, float(policy.max_score_delta)
        ):
            score_mismatches.append(subject)

    failed = (
        (policy.require_legacy_baseline and not legacy)
        or len(missing) > max(0, int(policy.max_missing_subjects))
        or len(extra) > max(0, int(policy.max_extra_subjects))
        or bool(suppression_mismatches)
        or bool(score_mismatches)
    )
    return ParityEvaluation(
        passed=not failed,
        status="PASS" if not failed else "REVIEW_REQUIRED",
        legacy_count=len(legacy),
        canonical_count=len(canonical),
        missing_subjects=missing,
        extra_subjects=extra,
        suppression_mismatches=tuple(suppression_mismatches),
        score_mismatches=tuple(score_mismatches),
        automatic_execution=False,
    )
