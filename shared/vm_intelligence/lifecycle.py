from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

def _manifest_candidates(root: Path, source: str):
    bot=root/"bots"/source
    if not bot.exists():
        return []
    rows=[]
    for p in bot.glob("**/BOT_MANIFEST.json"):
        data=_read_json(p) or {}
        if data.get("name") not in {None, source}:
            continue
        lifecycle=data.get("lifecycle") or {}
        if not lifecycle:
            continue
        entry=data.get("entrypoint")
        entry_exists=bool(entry and (p.parent/entry).is_file())
        confidence=str(data.get("entrypoint_confidence") or "").lower()
        version=str(data.get("version") or "")
        score=0
        if entry_exists: score+=100
        if confidence=="high": score+=50
        if version and version.lower()!="unknown": score+=20
        if data.get("classification")=="CANONICAL": score+=10
        # Prefer the manifest closest to the actual runnable files, not an outer
        # registry shadow manifest with entrypoint=null.
        score+=min(20,len(p.relative_to(bot).parts))
        rows.append((score,p,data))
    return sorted(rows,key=lambda x:(-x[0],str(x[1])))

def manifest_policy(root: str | Path, source: str) -> dict:
    root=Path(root)
    rows=_manifest_candidates(root,source)
    return dict((rows[0][2].get("lifecycle") or {})) if rows else {}

def validation_policy(root: str | Path, source: str, *, max_age_hours: int = 48) -> dict:
    root=Path(root)
    path=root/"diagnostics"/"full_validation.json"
    data=_read_json(path) or {}
    stamp=data.get("completed_at_utc")
    if stamp:
        try:
            dt=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
            if datetime.now(timezone.utc)-dt > timedelta(hours=max_age_hours):
                return {}
        except Exception:
            pass
    for row in data.get("supervisor_actions",[]):
        if row.get("service")==source:
            return dict(row.get("policy") or {})
    return {}

def effective_policy(root: str | Path, source: str) -> dict:
    """Resolve lifecycle policy without trusting outer/shadow manifests.

    Current runnable canonical manifests win. A recent full-validation policy
    fills any missing values and is used as fallback when no runnable manifest
    is available.
    """
    manifest=manifest_policy(root,source)
    validation=validation_policy(root,source)
    if manifest:
        merged=dict(validation)
        merged.update(manifest)
        return merged
    return validation

def all_effective_policies(root: str | Path, sources) -> dict[str,dict]:
    return {source:effective_policy(root,source) for source in sources}
