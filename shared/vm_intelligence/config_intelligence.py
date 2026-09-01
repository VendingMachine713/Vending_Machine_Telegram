from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib

class ConfigurationIntelligence:
    """Tracks configuration drift using hashes only; never stores .env values."""
    def __init__(self,store,root):self.store=store;self.root=Path(root)

    def _files(self):
        rows=[]
        for bot in (self.root/"bots").iterdir() if (self.root/"bots").exists() else []:
            if not bot.is_dir():continue
            for name in ("BOT_MANIFEST.json","VERSION.txt",".env"):
                p=bot/name
                if p.is_file():rows.append((f"{bot.name}:{name}",p))
        cfg=self.root/"config"/"vm_intelligence.json"
        if cfg.is_file():rows.append(("VM_Intelligence:config",cfg))
        return rows

    def refresh(self):
        now=datetime.now(timezone.utc).isoformat();changes=[];tracked=0
        with self.store.connect() as con:
            for key,p in self._files():
                try:digest=hashlib.sha256(p.read_bytes()).hexdigest()
                except Exception:continue
                tracked+=1
                old=con.execute("SELECT * FROM config_baselines WHERE config_key=?",(key,)).fetchone()
                if old and old["sha256"]!=digest:
                    changes.append({"config_key":key,"path":str(p.relative_to(self.root)),
                                    "changed_from":old["sha256"][:12],"changed_to":digest[:12]})
                    con.execute("""UPDATE config_baselines SET sha256=?,last_seen_utc=?,last_changed_utc=?
                        WHERE config_key=?""",(digest,now,now,key))
                elif old:
                    con.execute("UPDATE config_baselines SET last_seen_utc=? WHERE config_key=?",(now,key))
                else:
                    con.execute("""INSERT INTO config_baselines(
                        config_key,path,sha256,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?)""",
                        (key,str(p.relative_to(self.root)),digest,now,now))
        return {"tracked":tracked,"changes":changes,
                "privacy":"Only SHA-256 hashes and paths are persisted for .env files."}
