from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import collect_autoposter_evidence
from .db import PlatformDB
from .opportunity_intelligence import opportunities
from .paths import project_root

RULE_ID = "phase2.autoposter_opportunity"
RULE_VERSION = 1


def sync_autoposter_intelligence(root: Path | None = None, *, limit: int = 50) -> dict[str, Any]:
    """Refresh SAP evidence and emit passive review recommendations only.

    This function never writes to Smart Auto Poster-owned tables, never sends Telegram
    messages, and never accepts or executes its own recommendations.
    """
    root = root or project_root()
    evidence = collect_autoposter_evidence(root)
    if not evidence.get("available"):
        return {
            "available": False,
            "evidence": evidence,
            "recommendations_created_or_refreshed": 0,
            "automatic_execution": False,
        }

    db = PlatformDB(root=root)
    db.init()
    rows = [
        row for row in opportunities(root, limit=max(limit * 3, 100))
        if row["subject_type"] in {"destination", "campaign"}
    ]
    changed = 0
    blocked = 0
    for row in rows[: max(1, int(limit))]:
        if row["blocked"]:
            blocked += 1
            continue
        priority = min(100.0, max(0.0, float(row["opportunity_score"])))
        if priority < 35:
            continue
        subject_type = str(row["subject_type"])
        subject_id = str(row["subject_id"])
        db.upsert_recommendation(
            f"phase2:sap-opportunity:{subject_type}:{subject_id}",
            "autoposter_review",
            "Review this Smart Auto Poster opportunity in Mission Control before taking any action",
            "VM Brain found positive evidence for this SAP-related subject without an active blocking incident",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            subject_type=subject_type,
            subject_id=subject_id,
            priority=priority,
            confidence=float(row["confidence"]),
            evidence={
                "opportunity_score": row["opportunity_score"],
                "risk_score": row["risk_score"],
                "campaign_ids": row["campaign_ids"],
                "supporting_signals": [item["key"] for item in row["signals"]],
                "source": "vm_core.autoposter_intelligence",
                "automatic_send": False,
                "automatic_queue_mutation": False,
                "automatic_retry": False,
            },
            status="PROPOSED",
        )
        changed += 1
    return {
        "available": True,
        "evidence": evidence,
        "opportunities_considered": len(rows),
        "blocked_opportunities": blocked,
        "recommendations_created_or_refreshed": changed,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "smart_autoposter_database_written": False,
        "telegram_send_authority": False,
    }
