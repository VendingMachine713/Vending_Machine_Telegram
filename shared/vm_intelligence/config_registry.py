from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json

from .v42_schema import ensure_v42_schema

def _now():return datetime.now(timezone.utc).isoformat()

def _hash(path:Path):
    h=hashlib.sha256()
    try:
        with path.open("rb") as f:
            for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
        return h.hexdigest()
    except Exception:return None

class ConfigRegistry:
    """Hash-only configuration ownership registry. Secret-bearing values are never read into reports."""
    def __init__(self,store,root):self.store=store;self.root=Path(root);ensure_v42_schema(store)

    @staticmethod
    def _role(path:Path):
        n=path.name.lower()
        if n.startswith(".env"):return "environment"
        if "manifest" in n:return "manifest"
        if "config" in n or "settings" in n:return "configuration"
        return "supporting_config"

    def refresh(self,services):
        now=_now();rows=[];active=set()
        service_names={x["service"] for x in services}
        with self.store.connect() as con:
            previous=[dict(r) for r in con.execute("SELECT * FROM config_registry").fetchall()]
            for svc in services:
                paths=set(svc.get("config_paths") or [])
                if svc.get("manifest_path"):paths.add(svc["manifest_path"])
                for raw in sorted(paths,key=str.casefold):
                    p=Path(raw);key=hashlib.sha256(f"{svc['service']}|{str(p).casefold()}".encode()).hexdigest()[:24]
                    active.add(key)
                    secret=p.name.lower().startswith(".env") or any(x in p.name.lower() for x in ("secret","credential","token"))
                    row={"config_key":key,"service":svc["service"],"path":str(p),"sha256":_hash(p) if p.is_file() else None,
                         "role":self._role(p),"secret_bearing":secret,"exists":p.is_file(),"observed_at_utc":now}
                    rows.append(row)
                    con.execute("""INSERT INTO config_registry(config_key,service,path,sha256,role,secret_bearing,exists_flag,observed_at_utc,metadata_json)
                        VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(config_key) DO UPDATE SET service=excluded.service,path=excluded.path,sha256=excluded.sha256,
                          role=excluded.role,secret_bearing=excluded.secret_bearing,exists_flag=excluded.exists_flag,
                          observed_at_utc=excluded.observed_at_utc""",
                        (key,row["service"],row["path"],row["sha256"],row["role"],1 if secret else 0,
                         1 if row["exists"] else 0,now,"{}"))
            # A previously known config disappearing is itself an observation, not absence of data.
            for prev in previous:
                if prev["service"] not in service_names or prev["config_key"] in active:continue
                missing={**prev,"secret_bearing":bool(prev["secret_bearing"]),"exists":False,"observed_at_utc":now}
                missing.pop("exists_flag",None);missing.pop("metadata_json",None)
                rows.append(missing)
                con.execute("UPDATE config_registry SET exists_flag=0,observed_at_utc=? WHERE config_key=?",(now,prev["config_key"]))
        out=self.root/"state"/"config_registry.json";out.parent.mkdir(parents=True,exist_ok=True)
        # No config contents are ever serialized.
        out.write_text(json.dumps({"schema_version":1,"generated_at_utc":now,"configs":rows},indent=2),encoding="utf-8")
        return rows
