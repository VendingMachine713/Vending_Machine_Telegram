from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from .v4_schema import ensure_v4_schema

EXCLUDED = {"archive","backups","venv",".venv","__pycache__",".git","node_modules","runtime","sessions"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _excluded(path: Path) -> bool:
    return any(part.lower() in EXCLUDED for part in path.parts)


def _resolve(base: Path, value):
    if not value:
        return None
    p = Path(str(value))
    return p if p.is_absolute() else (base / p).resolve()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _topology_hash(service_root: Path, entrypoint: Path, manifest: Path | None) -> str:
    payload = {
        "service_root": service_root.resolve().as_posix(),
        "entrypoint": entrypoint.resolve().as_posix(),
        "manifest": manifest.resolve().as_posix() if manifest else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class RuntimeRegistry:
    def __init__(self, store, root):
        self.store = store
        self.root = Path(root)
        ensure_v4_schema(store)

    def _bridge(self):
        path = self.root / "state" / "runtime_bridge.json"
        return _read_json(path)

    def _discover_service(self, service: str):
        bot = self.root / "bots" / service
        if not bot.is_dir():
            return None
        candidates = []
        manifests = []
        for manifest in bot.glob("**/BOT_MANIFEST.json"):
            if _excluded(manifest):
                continue
            data = _read_json(manifest)
            if data.get("name") and str(data.get("name")) != service:
                continue
            manifests.append(manifest)
            ep = _resolve(manifest.parent, data.get("entrypoint"))
            if not ep or not ep.is_file():
                continue
            score = 0
            if str(data.get("classification") or "").upper() == "CANONICAL":
                score += 300
            if str(data.get("entrypoint_confidence") or "").lower() == "high":
                score += 100
            if manifest.parent == bot:
                score += 50
            if (manifest.parent / "tests").is_dir():
                score += 20
            score -= len(manifest.relative_to(bot).parts)
            candidates.append((score, manifest, data, ep))
        if not candidates:
            for name in ("main.py", "app.py"):
                for ep in bot.glob(f"**/{name}"):
                    if _excluded(ep):
                        continue
                    candidates.append((25 - len(ep.relative_to(bot).parts), None, {}, ep))
        bridge = self._bridge()
        bridge_row = next((x for x in bridge.get("services", []) if x.get("bot") == service), None)
        compatibility = None
        if bridge_row:
            compatibility = bridge_row.get("root_main")
            nested = bridge_row.get("nested") or {}
            bridge_ep = Path(str(nested.get("entrypoint_abs") or ""))
            bridge_manifest = Path(str(nested.get("manifest") or "")) if nested.get("manifest") else None
            if bridge_ep.is_file():
                # Runtime bridge is a compatibility surface only. The nested, regression-tested
                # target remains canonical for hashing, impact analysis and release intelligence.
                data = _read_json(bridge_manifest) if bridge_manifest and bridge_manifest.is_file() else {}
                manifest = bridge_manifest if bridge_manifest and bridge_manifest.is_file() else None
                ep = bridge_ep.resolve()
                score = 500
                policy = bridge_row.get("policy") or {}
                lifecycle = {
                    "auto_start": bool(policy.get("auto_start")),
                    "auto_restart": bool(policy.get("auto_restart")),
                }
            else:
                bridge_row = None
        if bridge_row is None:
            if not candidates:
                return {
                    "service": service,
                    "status": "unresolved",
                    "manifest_count": len(manifests),
                    "candidate_count": 0,
                }
            candidates.sort(key=lambda x: (-x[0], len(str(x[3])), str(x[3]).casefold()))
            score, manifest, data, ep = candidates[0]
            lifecycle = data.get("lifecycle") or {}
        runtime_id = hashlib.sha256(f"{service}|{ep.resolve().as_posix()}".encode()).hexdigest()[:20]
        return {
            "service": service,
            "runtime_id": runtime_id,
            "canonical_root": str(ep.parent.resolve()),
            "canonical_entrypoint": str(ep.resolve()),
            "compatibility_entrypoint": compatibility,
            "manifest_path": str(manifest.resolve()) if manifest else None,
            "version": data.get("version"),
            "managed": bool(lifecycle.get("auto_start") or lifecycle.get("auto_restart")),
            "auto_start": bool(lifecycle.get("auto_start")),
            "auto_restart": bool(lifecycle.get("auto_restart")),
            "discovery_confidence": min(1.0, max(0.25, score / 450.0)),
            "source_hash": _hash_file(ep),
            "topology_hash": _topology_hash(bot, ep, manifest),
            "status": "canonical",
            "manifest_count": len(manifests),
            "candidate_count": len(candidates),
            "nested_depth": max(0, len(ep.parent.relative_to(bot).parts)),
        }

    def refresh(self):
        now = _now()
        bots = self.root / "bots"
        rows = []
        if bots.is_dir():
            for bot in sorted((p for p in bots.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
                row = self._discover_service(bot.name)
                if not row:
                    continue
                rows.append(row)
        with self.store.connect() as con:
            for row in rows:
                if row.get("status") != "canonical":
                    continue
                con.execute(
                    """
                    INSERT INTO runtime_registry(service,runtime_id,canonical_root,canonical_entrypoint,
                        compatibility_entrypoint,manifest_path,version,managed,auto_start,auto_restart,
                        discovery_confidence,source_hash,topology_hash,status,observed_at_utc,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(service) DO UPDATE SET
                      runtime_id=excluded.runtime_id,
                      canonical_root=excluded.canonical_root,
                      canonical_entrypoint=excluded.canonical_entrypoint,
                      compatibility_entrypoint=excluded.compatibility_entrypoint,
                      manifest_path=excluded.manifest_path,
                      version=excluded.version,
                      managed=excluded.managed,
                      auto_start=excluded.auto_start,
                      auto_restart=excluded.auto_restart,
                      discovery_confidence=excluded.discovery_confidence,
                      source_hash=excluded.source_hash,
                      topology_hash=excluded.topology_hash,
                      status=excluded.status,
                      observed_at_utc=excluded.observed_at_utc,
                      metadata_json=excluded.metadata_json
                    """,
                    (
                        row["service"], row["runtime_id"], row["canonical_root"], row["canonical_entrypoint"],
                        row.get("compatibility_entrypoint"), row.get("manifest_path"), row.get("version"),
                        1 if row.get("managed") else 0, 1 if row.get("auto_start") else 0,
                        1 if row.get("auto_restart") else 0, float(row.get("discovery_confidence") or 0),
                        row.get("source_hash"), row.get("topology_hash"), row.get("status", "canonical"), now,
                        json.dumps({k: row[k] for k in ("manifest_count","candidate_count","nested_depth") if k in row}, sort_keys=True),
                    ),
                )
        self._write_state(rows)
        return rows

    def _write_state(self, rows):
        path = self.root / "state" / "runtime_registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "generated_at_utc": _now(), "services": rows}, indent=2), encoding="utf-8")

    def current(self):
        with self.store.connect() as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM runtime_registry ORDER BY service").fetchall()]
        for row in rows:
            try:
                row["metadata"] = json.loads(row.pop("metadata_json"))
            except Exception:
                row["metadata"] = {}
        return rows
