from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root


def _json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def entity_graph(root: Path | None = None, *, limit: int = 500) -> dict[str, Any]:
    """Build a privacy-minimised graph from shared metadata, signals and recommendations.

    The graph contains identifiers and derived operational metadata only. It does not copy
    Telegram message bodies or open bot-owned databases directly.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    edges: set[tuple[str, str, str, str, str]] = set()

    def node(kind: str, ident: Any, **attrs: Any) -> None:
        if ident in (None, ""):
            return
        key = (str(kind), str(ident))
        current = nodes.setdefault(key, {"type": key[0], "id": key[1]})
        for name, value in attrs.items():
            if value not in (None, "", [], {}):
                current[name] = value

    def edge(src_type: str, src_id: Any, relation: str, dst_type: str, dst_id: Any) -> None:
        if src_id in (None, "") or dst_id in (None, ""):
            return
        node(src_type, src_id)
        node(dst_type, dst_id)
        edges.add((str(src_type), str(src_id), str(relation), str(dst_type), str(dst_id)))

    with db.connect() as con:
        for row in con.execute("SELECT * FROM destinations ORDER BY id LIMIT ?", (max(1, limit),)):
            meta = _json(row["metadata_json"])
            node("destination", row["telegram_id"], title=row["title"], active=bool(row["active"]), source=row["source"], metadata=meta)
        for row in con.execute("SELECT * FROM accounts ORDER BY id LIMIT ?", (max(1, limit),)):
            node("account", row["label"], authorised=bool(row["authorized"]), source=row["source"], capabilities=_json(row["capabilities_json"]))
        for row in con.execute("SELECT * FROM intelligence_signals WHERE status='ACTIVE' ORDER BY score DESC LIMIT ?", (max(1, limit),)):
            if row["subject_type"] and row["subject_id"]:
                node(row["subject_type"], row["subject_id"])
                edge("signal", row["signal_key"], "about", row["subject_type"], row["subject_id"])
            node("signal", row["signal_key"], signal_type=row["signal_type"], score=float(row["score"]), confidence=float(row["confidence"]))
        for row in con.execute("SELECT * FROM intelligence_recommendations ORDER BY updated_at_utc DESC LIMIT ?", (max(1, limit),)):
            node("recommendation", row["recommendation_key"], recommendation_type=row["recommendation_type"], status=row["status"], priority=float(row["priority"]))
            if row["subject_type"] and row["subject_id"]:
                edge("recommendation", row["recommendation_key"], "about", row["subject_type"], row["subject_id"])
            evidence = _json(row["evidence_json"])
            campaign_id = evidence.get("campaign_id")
            account_key = evidence.get("account_key")
            if campaign_id not in (None, ""):
                edge("recommendation", row["recommendation_key"], "references", "campaign", campaign_id)
            if account_key not in (None, ""):
                edge("recommendation", row["recommendation_key"], "references", "account", account_key)
        for row in con.execute("SELECT * FROM incidents WHERE status='OPEN' ORDER BY last_seen_utc DESC LIMIT ?", (max(1, limit),)):
            node("incident", row["incident_key"], incident_type=row["incident_type"], severity=row["severity"], summary=row["summary"])
            if row["subject_type"] and row["subject_id"]:
                edge("incident", row["incident_key"], "about", row["subject_type"], row["subject_id"])

    type_counts: dict[str, int] = {}
    for item in nodes.values():
        type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1
    rendered_edges = [
        {"source": {"type": a, "id": b}, "relation": c, "target": {"type": d, "id": e}}
        for a, b, c, d, e in sorted(edges)
    ]
    return {
        "node_count": len(nodes),
        "edge_count": len(rendered_edges),
        "type_counts": type_counts,
        "nodes": sorted(nodes.values(), key=lambda item: (item["type"], item["id"])),
        "edges": rendered_edges,
        "message_content_copied": False,
        "bot_databases_written": False,
        "external_action_authority": False,
    }
