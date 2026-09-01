from __future__ import annotations
from pathlib import Path
import hashlib,json
from .events import utc_now_iso
from .integrated_schema import ensure_v3_schema

class ReleaseIntelligence:
    def __init__(self,store,root):
        self.store=store; self.root=Path(root); ensure_v3_schema(store)

    def _hash_source(self,folder):
        h=hashlib.sha256()
        for p in sorted(folder.rglob("*.py")):
            if any(x.lower() in {"venv",".venv","__pycache__","backups","archive",".git","runtime"} for x in p.parts):
                continue
            try:
                h.update(str(p.relative_to(folder)).encode());h.update(p.read_bytes())
            except Exception:pass
        return h.hexdigest()

    def _version(self,folder):
        manifest=folder/"BOT_MANIFEST.json"
        if manifest.exists():
            try:
                d=json.loads(manifest.read_text(encoding="utf-8-sig"))
                if d.get("version"):return str(d["version"])
            except Exception:pass
        version=folder/"VERSION.txt"
        if version.exists():
            try:return version.read_text(encoding="utf-8-sig").strip()[:80]
            except Exception:pass
        return None

    def refresh(self,current_score=None):
        changes=[];bots=self.root/"bots"
        if not bots.exists():return changes
        with self.store.connect() as con:
            for folder in sorted(x for x in bots.iterdir() if x.is_dir()):
                version=self._version(folder);digest=self._hash_source(folder);now=utc_now_iso()
                old=con.execute("SELECT * FROM release_baselines WHERE source=?",(folder.name,)).fetchone()
                if old and old["source_hash"]!=digest:
                    change={"source":folder.name,"previous_version":old["version"],"version":version,
                            "previous_hash":old["source_hash"],"source_hash":digest,"changed":True}
                    changes.append(change)
                    exists=con.execute("SELECT 1 FROM release_events WHERE source=? AND source_hash=? LIMIT 1",
                                       (folder.name,digest)).fetchone()
                    if not exists:
                        con.execute("""INSERT INTO release_events(
                            source,detected_at_utc,previous_version,version,previous_hash,source_hash,baseline_score)
                            VALUES(?,?,?,?,?,?,?)""",
                            (folder.name,now,old["version"],version,old["source_hash"],digest,current_score))
                con.execute("""INSERT OR REPLACE INTO release_baselines(
                    source,version,source_hash,observed_at_utc,metadata_json) VALUES(?,?,?,?,?)""",
                    (folder.name,version,digest,now,"{}"))
        return changes
